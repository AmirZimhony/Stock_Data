"""Mocked tests for the yfinance scraper, the MongoDB writer, and the CLI."""

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from yfinance.exceptions import YFRateLimitError

import stock_functions as sf
import yfinance_scraper as ys

# Field names and types of a stored Finviz document (stock_data.nasdaq_stocks).
STORED_TYPES = {
    "serial_number": int,
    "ticker": str,
    "company": str,
    "sector": str,
    "industry": str,
    "country": str,
    "market_cap": str,
    "pe_ratio": str,
    "price": float,
    "change": str,
    "volume": str,
    "numOfRisingDays": str,
    "accumulatedChange": str,
    "timestamp": datetime,
}
DOCUMENT_FIELDS = set(STORED_TYPES) - {
    "numOfRisingDays",
    "accumulatedChange",
    "timestamp",
}

NASDAQ_LISTED = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZXZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
AACIU|Armada Acquisition Corp. III - Units|G|N|N|100|N|N
AACIW|Armada Acquisition Corp. III - Warrant|G|N|N|100|N|N
AACPR|Apogee Acquisition Corp - Rights|G|N|N|100|N|N
ADAMG|Adamas Trust, Inc. - 9.125% Senior Notes Due 2030|G|N|N|100|N|N
ACGLN|Arch Capital Group Ltd. - Depositary Shares, each Representing a 1/1,000th Interest in a 4.550% Non-Cumulative Preferred Share, Series G|G|N|N|100|N|N
ARCC|Ares Capital Corporation - Closed End Fund|Q|N|N|100|N|N
ARLP|Alliance Resource Partners, L.P. - Common Units Representing Limited Partnership Interests|Q|N|N|100|N|N
File Creation Time: 1105202610:01|||||||
"""
OTHER_LISTED = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK=B
BF.B|Brown Forman Corp Class B Common Stock|N|BF.B|N|100|N|BF=B
ABR$D|Arbor Realty Trust 6.375% Series D Cumulative Redeemable Preferred Stock|N|ABR$D|N|100|N|ABR-D
KTN|Structured Products Corp 8.205% CorTS 8.205% Corporate Backed Trust Securities (CorTS)|N|KTN|N|100|N|KTN
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
ARCA|Some Arca Listed Inc. Common Stock|P|ARCA|N|100|N|ARCA
IMO|Imperial Oil Limited Common Stock|A|IMO|N|100|N|IMO
File Creation Time: 1105202610:01|||||||
"""


def quote(symbol, **overrides):
    base = {
        "symbol": symbol,
        "quoteType": "EQUITY",
        "longName": "Apple Inc.",
        "marketCap": 5_100_810_000_000,
        "trailingPE": 38.9412,
        "regularMarketPrice": 349.51,
        "regularMarketPreviousClose": 331.889,
        "regularMarketVolume": 88_958_281,
    }
    base.update(overrides)
    return base


class MemoryCollection:
    """The subset of pymongo.Collection the writers use, with $set/$setOnInsert."""

    def __init__(self, docs=None):
        self.docs = {doc["ticker"]: dict(doc) for doc in docs or []}

    @staticmethod
    def _matches(doc, query):
        for key, value in query.items():
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def find_one(self, query):
        found = [d for d in self.docs.values() if self._matches(d, query)]
        return dict(found[0]) if found else None

    def find(self, query, projection=None):
        return [dict(d) for d in self.docs.values() if self._matches(d, query)]

    def update_one(self, query, update, upsert=False):
        doc = next(
            (d for d in self.docs.values() if self._matches(d, query)),
            None,
        )
        if doc is None:
            if not upsert:
                return SimpleNamespace(
                    matched_count=0, modified_count=0, upserted_id=None
                )
            doc = {"ticker": query["ticker"], **update.get("$setOnInsert", {})}
            doc.update(update.get("$set", {}))
            self.docs[doc["ticker"]] = doc
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=1)
        before = dict(doc)
        doc.update(update.get("$set", {}))
        return SimpleNamespace(
            matched_count=1, modified_count=int(doc != before), upserted_id=None
        )


def universe():
    return ys.parse_listings(NASDAQ_LISTED, OTHER_LISTED)


def no_sleep(_seconds):
    return None


# 1. Exact MongoDB schema compatibility


def test_daily_document_has_the_finviz_fields_and_stored_types():
    sf.reset_aggregate_counts()
    collection = MemoryCollection()
    ys.run_daily(
        collection,
        max_workers=2,
        universe=(["AAPL"], {}),
        fetch=lambda batch: {"AAPL": quote("AAPL")},
        sleep=no_sleep,
    )
    stored = collection.docs["AAPL"]
    assert set(stored) == set(STORED_TYPES)
    for field, kind in STORED_TYPES.items():
        assert isinstance(stored[field], kind), field


def test_build_document_has_exactly_the_scraper_fields():
    document = ys.build_document(1, "AAPL", quote("AAPL"))
    assert set(document) == DOCUMENT_FIELDS


# 2. Field types and semantics (Finviz display formats)


def test_formats_match_the_stored_finviz_strings():
    document = ys.build_document(16, "AAPL", quote("AAPL"))
    assert document == {
        "serial_number": 16,
        "ticker": "AAPL",
        "company": "Apple Inc",
        "sector": "-",
        "industry": "-",
        "country": "-",
        "market_cap": "5100.81B",
        "pe_ratio": "38.94",
        "price": 349.51,
        "change": "5.31%",
        "volume": "88,958,281",
    }


def test_numeric_edge_formats():
    assert ys.format_market_cap(149_970_000) == "149.97M"
    assert ys.format_market_cap(5_450_000) == "5.45M"
    assert ys.format_market_cap(1_000_000_000) == "1.00B"
    assert ys.format_change(98.8, 100) == "-1.20%"
    assert ys.format_change(100, 100) == "0.00%"
    assert ys.format_pe(-3.2) == "-"
    assert ys.format_volume(0) == "0"
    assert ys.clean_company("Amazon.com, Inc.") == "Amazon.com Inc"
    assert ys.clean_company("Berkshire Hathaway Inc.") == "Berkshire Hathaway Inc"


def test_profile_labels_map_to_finviz_values():
    assert ys._label("United States", ys.COUNTRY_LABELS) == "USA"
    assert ys._label("Canada", ys.COUNTRY_LABELS) == "Canada"
    assert ys._label("Financial Services", ys.SECTOR_LABELS) == "Financial"
    assert ys._label("Technology", ys.SECTOR_LABELS) == "Technology"


# 3. Missing metadata


def test_missing_quote_values_use_finviz_placeholders():
    document = ys.build_document(
        1,
        "XYZ",
        {
            "symbol": "XYZ",
            "quoteType": "EQUITY",
            "marketCap": None,
            "regularMarketPrice": float("nan"),
        },
    )
    assert document["company"] == "-"
    assert document["market_cap"] == "-"
    assert document["pe_ratio"] == "-"
    assert document["price"] is None
    assert document["change"] == "-"
    assert document["volume"] == "-"


def test_missing_profile_values_never_overwrite_stored_values():
    collection = MemoryCollection(
        [{"ticker": "AAPL", "company": "Apple Inc", "sector": "Technology"}]
    )
    updated = sf.update_profiles(
        {"AAPL": {"company": "-", "sector": "-", "industry": "Consumer Electronics"}},
        collection,
    )
    assert updated == 1
    assert collection.docs["AAPL"]["sector"] == "Technology"
    assert collection.docs["AAPL"]["company"] == "Apple Inc"
    assert collection.docs["AAPL"]["industry"] == "Consumer Electronics"


# 4. Invalid tickers


def test_tickers_without_a_quote_are_skipped_not_failed():
    sf.reset_aggregate_counts()
    collection = MemoryCollection()
    summary = ys.run_daily(
        collection,
        max_workers=1,
        universe=(["AAPL", "GONE"], {}),
        fetch=lambda batch: {"AAPL": quote("AAPL")},
        sleep=no_sleep,
    )
    assert summary["invalid"] == ["GONE"]
    assert summary["failed"] == []
    assert set(collection.docs) == {"AAPL"}


def test_profile_404_is_an_empty_profile(monkeypatch):
    class NotFound(Exception):
        response = SimpleNamespace(status_code=404)

    class FakeData:
        def get_raw_json(self, *args, **kwargs):
            raise NotFound("404")

    monkeypatch.setattr(ys, "YfData", FakeData)
    assert ys._profile_fetcher()("GONE") == {}


# 5. ETF and non-company instrument exclusion


def test_universe_keeps_common_stocks_only():
    tickers, breakdown = universe()
    assert tickers == ["AAPL", "ARCC", "ARLP", "BF-B", "BRK-B", "IMO"]
    assert breakdown == {
        "common": 6,
        "etf": 2,
        "test_issue": 1,
        "unit": 1,
        "warrant": 1,
        "right": 1,
        "debt": 1,
        "preferred": 2,
        "structured_product": 1,
        "other_exchange": 1,
    }


def test_non_equity_quotes_are_skipped():
    sf.reset_aggregate_counts()
    collection = MemoryCollection()
    summary = ys.run_daily(
        collection,
        max_workers=1,
        universe=(["AAPL", "CEF"], {}),
        fetch=lambda batch: {
            "AAPL": quote("AAPL"),
            "CEF": quote("CEF", quoteType="MUTUALFUND"),
        },
        sleep=no_sleep,
    )
    assert summary["non_equity"] == ["CEF"]
    assert set(collection.docs) == {"AAPL"}


# 6. Partial failures


def test_failed_quote_batch_keeps_other_batches(monkeypatch):
    monkeypatch.setattr(ys, "QUOTE_BATCH_SIZE", 1)
    sf.reset_aggregate_counts()
    collection = MemoryCollection()
    sleeps = []

    def fetch(batch):
        if batch == ["BAD"]:
            raise ConnectionError("reset")
        return {batch[0]: quote(batch[0])}

    summary = ys.run_daily(
        collection,
        max_workers=1,
        universe=(["AAPL", "BAD", "MSFT"], {}),
        fetch=fetch,
        sleep=sleeps.append,
    )
    assert summary["failed"] == ["BAD"]
    assert set(collection.docs) == {"AAPL", "MSFT"}
    assert sleeps == [1, 2]


def test_quote_rate_limit_waits_before_retrying():
    calls = []

    def fetch(batch):
        calls.append(batch)
        if len(calls) == 1:
            raise YFRateLimitError()
        return {"AAPL": quote("AAPL")}

    sleeps = []
    quotes, failed = ys.fetch_quotes(["AAPL"], fetch=fetch, sleep=sleeps.append)
    assert set(quotes) == {"AAPL"} and failed == []
    assert sleeps == [ys.RATE_LIMIT_PAUSE_SECONDS]


def test_weekly_pauses_once_then_stops_on_second_rate_limit():
    collection = MemoryCollection(
        [{"ticker": t, "sector": "-"} for t in ("AAA", "BBB", "CCC", "DDD")]
    )
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if ticker in ("BBB", "CCC") and calls.count(ticker) == 1:
            raise YFRateLimitError()
        return {"sector": "Technology"}

    sleeps = []
    summary = ys.run_weekly(
        collection,
        universe=(["AAA", "BBB", "CCC", "DDD"], {}),
        fetch=fetch,
        sleep=sleeps.append,
    )
    assert summary["stopped"] is True
    assert summary["fetched"] == 2
    assert sleeps == [ys.RATE_LIMIT_PAUSE_SECONDS]
    assert collection.docs["BBB"]["sector"] == "Technology"
    assert collection.docs["DDD"]["sector"] == "-"


def test_weekly_refreshes_missing_profiles_first_and_skips_unknown_tickers():
    collection = MemoryCollection(
        [
            {"ticker": "AAA", "sector": "Technology"},
            {"ticker": "BBB", "sector": "-"},
        ]
    )
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return {"sector": "Healthcare"}

    summary = ys.run_weekly(
        collection, universe=(["AAA", "BBB", "NEW"], {}), fetch=fetch, sleep=no_sleep
    )
    assert calls == ["BBB", "AAA"]
    assert summary["requested"] == 2
    assert "NEW" not in collection.docs


# 7. MongoDB writes and upserts


def test_daily_insert_sets_profile_fields_on_insert_only():
    sf.reset_aggregate_counts()
    collection = MemoryCollection(
        [
            {
                "ticker": "AAPL",
                "company": "Apple Inc",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "country": "USA",
                "price": 300.0,
                "numOfRisingDays": "2",
                "accumulatedChange": "4.0",
            }
        ]
    )
    ys.run_daily(
        collection,
        max_workers=1,
        universe=(["AAPL", "MSFT"], {}),
        fetch=lambda batch: {
            "AAPL": quote("AAPL", longName="Renamed Inc.", regularMarketPrice=303.0),
            "MSFT": quote("MSFT", longName="Microsoft Corporation"),
        },
        sleep=no_sleep,
    )
    apple = collection.docs["AAPL"]
    assert apple["company"] == "Apple Inc"
    assert apple["sector"] == "Technology"
    assert apple["price"] == 303.0
    assert apple["numOfRisingDays"] == "3"
    assert apple["accumulatedChange"] == "5.0"

    microsoft = collection.docs["MSFT"]
    assert microsoft["company"] == "Microsoft Corporation"
    assert microsoft["sector"] == microsoft["industry"] == microsoft["country"] == "-"
    assert microsoft["numOfRisingDays"] == "1"
    assert sf.get_aggregate_counts() == {"total_read": 2, "inserted": 1, "updated": 1}


def _freeze_now(monkeypatch, moment):
    monkeypatch.setattr(sf, "_utcnow", lambda: moment)


def _stored_quote(ticker, price, rising_days, timestamp):
    document = ys.build_document(1, ticker, quote(ticker, regularMarketPrice=price))
    document.update(
        {
            "numOfRisingDays": rising_days,
            "accumulatedChange": "4.0",
            "timestamp": timestamp,
            "price": price,
        }
    )
    return document


def test_prior_day_same_price_records_the_new_day(monkeypatch):
    yesterday = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)
    today = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)
    _freeze_now(monkeypatch, today)
    collection = MemoryCollection([_stored_quote("AAPL", 349.51, "3", yesterday)])
    document = ys.build_document(1, "AAPL", quote("AAPL"))
    sf.write_or_update_to_mongo([document], collection)
    sf.write_or_update_to_mongo([document], collection)
    stored = collection.docs["AAPL"]
    assert stored["numOfRisingDays"] == "3"
    assert stored["accumulatedChange"] == "4.0"
    assert stored["timestamp"] == today
    assert stored["price"] == 349.51


def test_same_day_price_move_does_not_increment_rising_days(monkeypatch):
    today = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)
    _freeze_now(monkeypatch, today)
    collection = MemoryCollection([_stored_quote("AAPL", 100.0, "2", today)])
    document = ys.build_document(1, "AAPL", quote("AAPL", regularMarketPrice=101.5))
    sf.write_or_update_to_mongo([document], collection)
    stored = collection.docs["AAPL"]
    assert stored["numOfRisingDays"] == "2"
    assert stored["accumulatedChange"] == "4.0"
    assert stored["price"] == 101.5


def test_same_price_rerun_does_not_increment_rising_days():
    sf.reset_aggregate_counts()
    collection = MemoryCollection()
    run = dict(
        max_workers=1,
        universe=(["AAPL"], {}),
        fetch=lambda batch: {"AAPL": quote("AAPL")},
        sleep=no_sleep,
    )
    ys.run_daily(collection, **run)
    ys.run_daily(collection, **run)
    assert collection.docs["AAPL"]["numOfRisingDays"] == "1"


def test_legacy_documents_still_set_every_field():
    collection = MemoryCollection(
        [{"ticker": "AAPL", "sector": "-", "price": 1.0, "numOfRisingDays": "0"}]
    )
    document = ys.build_document(1, "AAPL", quote("AAPL"))
    document["sector"] = "Technology"
    sf.write_or_update_to_mongo([document], collection)
    assert collection.docs["AAPL"]["sector"] == "Technology"


# 8. Staging/production CLI behavior


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __getitem__(self, db_name):
        return {
            name: (db_name, name)
            for name in ("nasdaq_stocks", "nasdaq_stocks_staging", "stocks_test")
        }


def configured(monkeypatch, argv):
    import config

    monkeypatch.setenv("db_url", "mongodb://localhost/test")
    monkeypatch.setattr(config, "MongoClient", FakeClient)
    config.configure(config.parse_args(argv))
    return config


STAGING = [
    "--env",
    "staging",
    "--db-name",
    "stock_staging",
    "--collection-name",
    "nasdaq_stocks_staging",
    "--max-workers",
    "5",
]
PROD = [
    "--env",
    "prod",
    "--db-name",
    "stock_data",
    "--collection-name",
    "nasdaq_stocks",
    "--max-workers",
    "30",
]


def test_staging_cli_targets_staging_with_limit(monkeypatch):
    config = configured(monkeypatch, STAGING + ["--mode", "daily", "--limit", "500"])
    assert config.collection == ("stock_staging", "nasdaq_stocks_staging")
    assert config.config["mode"] == "daily"
    assert config.config["limit"] == 500


def test_prod_cli_targets_prod_without_limit(monkeypatch):
    config = configured(monkeypatch, PROD + ["--mode", "weekly"])
    assert config.collection == ("stock_data", "nasdaq_stocks")
    assert config.config["mode"] == "weekly"
    assert config.config["limit"] is None


def test_dev_json_defaults(monkeypatch):
    config = configured(monkeypatch, [])
    dev = json.loads((Path(config.__file__).parent / "dev.json").read_text())
    assert config.collection == (dev["DB_name"], dev["collection_name"])
    assert config.config["mode"] == "daily"
    assert config.config["limit"] == dev["limit"]


@pytest.mark.parametrize(
    "argv",
    [
        ["--mode", "monthly"],
        ["--end-index", "501"],
    ],
)
def test_invalid_or_removed_flags_are_rejected(argv):
    import config

    with pytest.raises(SystemExit):
        config.parse_args(argv)


def test_limit_must_be_positive(monkeypatch):
    with pytest.raises(ValueError, match="--limit"):
        configured(monkeypatch, STAGING + ["--limit", "0"])


def import_main(monkeypatch, argv):
    import config

    monkeypatch.setenv("db_url", "mongodb://localhost/test")
    monkeypatch.setattr(config, "MongoClient", FakeClient)
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    sys.modules.pop("main", None)
    main_mod = importlib.import_module("main")
    gauges = []
    monkeypatch.setattr(
        main_mod.stocker_metrics, "gauge", lambda *args, **kwargs: gauges.append(args)
    )
    return main_mod, gauges


def daily_summary(**overrides):
    summary = {
        "requested": 1,
        "documents": 1,
        "invalid": [],
        "non_equity": [],
        "failed": [],
        "breakdown": {},
    }
    summary.update(overrides)
    return summary


def test_main_daily_dispatch_and_metrics(monkeypatch):
    main_mod, gauges = import_main(monkeypatch, STAGING + ["--limit", "500"])
    seen = {}

    def fake_daily(collection, max_workers, limit=None):
        seen.update(collection=collection, max_workers=max_workers, limit=limit)
        sf.write_or_update_to_mongo(
            [ys.build_document(1, "AAPL", quote("AAPL"))], MemoryCollection()
        )
        return daily_summary()

    monkeypatch.setattr(main_mod, "run_daily", fake_daily)
    main_mod.main()
    assert seen == {
        "collection": ("stock_staging", "nasdaq_stocks_staging"),
        "max_workers": 5,
        "limit": 500,
    }
    assert [g[0] for g in gauges] == [
        "stocks.read",
        "stocks.inserted",
        "stocks.updated",
    ]


def test_main_daily_fails_on_partial_scrape(monkeypatch):
    main_mod, gauges = import_main(monkeypatch, PROD)

    def fake_daily(collection, max_workers, limit=None):
        sf.write_or_update_to_mongo(
            [ys.build_document(1, "AAPL", quote("AAPL"))], MemoryCollection()
        )
        return daily_summary(failed=["MSFT"])

    monkeypatch.setattr(main_mod, "run_daily", fake_daily)
    with pytest.raises(RuntimeError, match="Scrape incomplete"):
        main_mod.main()
    assert gauges == []


def test_main_daily_fails_when_nothing_scraped(monkeypatch):
    main_mod, _ = import_main(monkeypatch, PROD)
    monkeypatch.setattr(
        main_mod, "run_daily", lambda *a, **k: daily_summary(documents=0)
    )
    with pytest.raises(RuntimeError, match="No stock data scraped"):
        main_mod.main()


def test_main_weekly_dispatch(monkeypatch):
    main_mod, gauges = import_main(monkeypatch, PROD + ["--mode", "weekly"])
    monkeypatch.setattr(
        main_mod,
        "run_weekly",
        lambda collection, limit=None: {
            "requested": 3,
            "fetched": 3,
            "updated": 2,
            "failed": [],
            "stopped": False,
        },
    )
    monkeypatch.setattr(
        main_mod, "run_daily", lambda *a, **k: pytest.fail("daily must not run")
    )
    main_mod.main()
    assert gauges == [("profiles.fetched", 3), ("profiles.updated", 2)]


def test_main_weekly_fails_when_no_profile_fetched(monkeypatch):
    main_mod, _ = import_main(monkeypatch, PROD + ["--mode", "weekly"])
    monkeypatch.setattr(
        main_mod,
        "run_weekly",
        lambda collection, limit=None: {
            "requested": 3,
            "fetched": 0,
            "updated": 0,
            "failed": [],
            "stopped": True,
        },
    )
    with pytest.raises(RuntimeError, match="No profiles fetched"):
        main_mod.main()
