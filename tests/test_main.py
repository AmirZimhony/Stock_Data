import os
import sys
from pathlib import Path
from unittest import mock

import importlib
from datetime import datetime, timezone

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def import_main_with_mocks():
    """Import main with a fake Mongo client and DB_URI set (re-imports cleanly per call)."""
    sys.argv = ["main.py"]

    class FakeCollection:
        def __init__(self):
            self.updated = []
            self._by_serial = {}

        def find_one(self, query):
            return self._by_serial.get(query.get("serial_number"))

        def update_one(self, query, update, upsert=False):
            self.updated.append((query, update, upsert))

    class FakeDatabase:
        def __init__(self):
            self._collections = {}

        def __getitem__(self, name):
            if name not in self._collections:
                self._collections[name] = FakeCollection()
            return self._collections[name]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._dbs = {}

        def __getitem__(self, name):
            if name not in self._dbs:
                self._dbs[name] = FakeDatabase()
            return self._dbs[name]

    env = {"db_url": "mongodb://localhost/test"}
    with mock.patch.dict(os.environ, env, clear=False):
        with mock.patch("pymongo.MongoClient", FakeClient):
            if "main" in sys.modules:
                del sys.modules["main"]
            return importlib.import_module("main")


def test_get_data_parses_and_invokes_write(monkeypatch):
    import_main_with_mocks()
    import stock_functions as sf

    # Header row includes a "Flag" column (as Finviz added) to verify it's
    # ignored and the remaining fields still line up correctly by header name.
    # The ticker cell mimics Finviz's real markup: a company-logo <img> whose
    # accessibility text repeats the ticker, plus the visible tab-link anchor.
    html = (
        "<table class='screener_table'>"
        "<tr valign='middle'>"
        "<th>No.</th><th>Ticker</th><th>Company</th><th>Sector</th>"
        "<th>Industry</th><th>Country</th><th>Market Cap</th><th>P/E</th>"
        "<th>Price</th><th>Change</th><th>Volume</th><th>Flag</th>"
        "</tr>"
        "<tr valign='top'>"
        "<td>1</td>"
        "<td>"
        "<a class='company-ticker'><img alt='AAPL logo'><span>AAPL</span></img></a>"
        "<a class='tab-link'>AAPL</a>"
        "</td>"
        "<td>Apple Inc.</td>"
        "<td>Technology</td>"
        "<td>Consumer Electronics</td>"
        "<td>USA</td>"
        "<td>3.0T</td>"
        "<td>30.0</td>"
        "<td>200.50</td>"
        "<td>+1.23%</td>"
        "<td>50,000,000</td>"
        "<td></td>"
        "</tr></table>"
    )

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    expected_url = "https://example.com/screener?v=111"

    def fake_get(url, proxies=None, headers=None, timeout=None):
        assert url == expected_url
        assert proxies == {"http": "http://proxy.example:80", "https": "http://proxy.example:80"}
        return FakeResponse(html, 200)

    called = {"data": None}

    def fake_write(page_data, collection):
        # get_data clears page_data after the write; keep a snapshot for assertions
        called["data"] = list(page_data)

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", expected_url)
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    sf.get_data(1, None)

    assert called["data"] is not None, "write_or_update_to_mongo was not called"
    assert isinstance(called["data"], list) and len(called["data"]) == 1
    stock = called["data"][0]
    assert stock["serial_number"] == 1
    assert stock["ticker"] == "AAPL"
    assert stock["company"] == "Apple Inc."
    assert stock["sector"] == "Technology"
    assert stock["industry"] == "Consumer Electronics"
    assert stock["country"] == "USA"
    assert stock["market_cap"] == "3.0T"
    assert stock["pe_ratio"] == "30.0"
    assert stock["price"] == 200.50
    assert stock["change"] == "+1.23%"
    assert stock["volume"] == "50,000,000"


def test_get_data_skips_write_on_unexpected_page(monkeypatch):
    """Simulates a blocked/changed response (no screener table) and expects a safe no-op."""
    import_main_with_mocks()
    import stock_functions as sf

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    def fake_get(url, proxies=None, headers=None, timeout=None):
        return FakeResponse("<html><body>Access to this page has been denied</body></html>", 200)

    invoked = {"called": False}

    def fake_write(page_data, collection):
        invoked["called"] = True

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    sf.get_data(1, None)

    assert invoked["called"] is False


def test_get_data_retries_after_request_exception(monkeypatch):
    """A transient error (e.g. ProxyError) should be retried, not abort immediately."""
    import_main_with_mocks()
    import stock_functions as sf

    html = (
        "<table class='screener_table'>"
        "<tr valign='middle'>"
        "<th>No.</th><th>Ticker</th><th>Company</th><th>Sector</th>"
        "<th>Industry</th><th>Country</th><th>Market Cap</th><th>P/E</th>"
        "<th>Price</th><th>Change</th><th>Volume</th>"
        "</tr>"
        "<tr valign='top'>"
        "<td>1</td><td>AAPL</td><td>Apple Inc.</td><td>Technology</td>"
        "<td>Consumer Electronics</td><td>USA</td><td>3.0T</td><td>30.0</td>"
        "<td>200.50</td><td>+1.23%</td><td>50,000,000</td>"
        "</tr></table>"
    )

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    calls = {"count": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise sf.requests.exceptions.ProxyError("Cannot connect to proxy.")
        return FakeResponse(html, 200)

    called = {"data": None}

    def fake_write(page_data, collection):
        called["data"] = list(page_data)

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    sf.get_data(1, None)

    assert calls["count"] == 3, "expected 2 failures then a successful 3rd attempt"
    assert called["data"] is not None, "should have recovered and written data after retrying"
    assert called["data"][0]["ticker"] == "AAPL"


def test_get_data_gives_up_after_repeated_exceptions(monkeypatch):
    """If every attempt raises, get_data should stop after 6 tries and not crash."""
    import_main_with_mocks()
    import stock_functions as sf

    calls = {"count": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["count"] += 1
        raise sf.requests.exceptions.ProxyError("Cannot connect to proxy.")

    invoked = {"called": False}

    def fake_write(page_data, collection):
        invoked["called"] = True

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    sf.get_data(1, None)

    assert calls["count"] == 6, "expected 1 initial attempt + 5 retries"
    assert invoked["called"] is False


def test_write_or_update_to_mongo_updates_accumulated_and_rising(monkeypatch):
    import_main_with_mocks()
    import stock_functions as sf

    class MemoryCollection:
        def __init__(self):
            self.storage = {
                "AAPL": {
                    "ticker": "AAPL",
                    "price": 200.0,
                    "numOfRisingDays": "2",
                    "accumulatedChange": "4.0",
                }
            }
            self.updates = []

        def find_one(self, query):
            return self.storage.get(query.get("ticker"))

        def update_one(self, query, update, upsert=False):
            self.updates.append((query, update, upsert))

    fake_collection = MemoryCollection()

    page_data = [
        {
            "serial_number": 1,
            "ticker": "AAPL",
            "company": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "USA",
            "market_cap": "3.0T",
            "pe_ratio": "30.0",
            "price": 200.50,
            "change": "+1.00%",
            "volume": "50,000,000",
        }
    ]

    before = datetime.now(timezone.utc)
    sf.write_or_update_to_mongo(page_data, fake_collection)
    after = datetime.now(timezone.utc)

    assert len(fake_collection.updates) == 1
    query, update, upsert = fake_collection.updates[0]
    assert query == {"ticker": "AAPL", "numOfRisingDays": "2"}
    assert upsert is False
    set_values = update.get("$set", {})
    assert set_values.get("numOfRisingDays") == "3"
    # actual change from price 200.0 -> 200.50 is 0.25%; accumulated 4.0 + 0.25
    assert set_values.get("accumulatedChange") == "4.25"
    write_timestamp = set_values.get("timestamp")
    assert isinstance(write_timestamp, datetime) and write_timestamp.tzinfo is not None
    assert before <= write_timestamp <= after


def test_live_scraper_parses_real_finviz_page(monkeypatch):
    """The only test in this suite that hits the real Finviz site (exactly one request).

    Exercises the actual get_data parser against live HTML to catch column/layout
    changes (e.g. a new column shifting indexes) that mocked tests can't detect.
    """
    url = os.getenv("nasdaq_scraping_url")
    proxy_url = os.getenv("proxy_url")
    if not url or not proxy_url:
        raise ValueError(
            "nasdaq_scraping_url and proxy_url are required (e.g. in .env at repo root)"
        )

    import_main_with_mocks()
    import stock_functions as sf

    captured = {"data": None}

    def fake_write(page_data, collection):
        captured["data"] = list(page_data)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)

    sf.get_data(1, None)  # exactly one real HTTP request to Finviz

    assert captured["data"], "expected at least one parsed stock row from the live page"

    tickers = [row["ticker"] for row in captured["data"]]
    assert all(tickers), "every row should have a non-empty ticker"
    assert len(tickers) == len(set(tickers)), "scraper returned duplicate tickers on one page"

    first = captured["data"][0]
    assert first["serial_number"] == 1
    assert first["company"], "company should be parsed, not the ticker or blank"
    assert first["price"] is None or isinstance(first["price"], float)
    assert first["change"] == "-" or first["change"].endswith("%")
    assert first["volume"], "volume should be parsed"
