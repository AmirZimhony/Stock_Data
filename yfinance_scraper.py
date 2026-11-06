"""
NASDAQ, NYSE, and NYSE American common stocks from Yahoo Finance (yfinance).

Daily: batched quote requests for price, change, volume, market cap, and P/E.
Weekly: one quoteSummary request per ticker for company, sector, industry,
and country. Documents keep the Finviz display formats stored in MongoDB.
"""

import logging
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests
from yfinance.data import YfData
from yfinance.exceptions import YFRateLimitError

from logging_config import get_logger
from stock_functions import PROFILE_FIELDS, update_profiles, write_or_update_to_mongo

logger = get_logger(__name__)
logging.getLogger("yfinance").setLevel(logging.WARNING)

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
PROFILE_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"

# Q = Nasdaq (nasdaqlisted.txt); N = NYSE and A = NYSE American (otherlisted.txt).
EXCHANGES = {"Q", "N", "A"}
QUOTE_BATCH_SIZE = 50
WRITE_CHUNK_SIZE = 100
MAX_ATTEMPTS = 3
RATE_LIMIT_PAUSE_SECONDS = 60

# Security-name markers for listings that are not a company's common equity.
# Checked in order; the first match names the exclusion category.
_EXCLUDED_SECURITIES = (
    ("preferred", r"\bpreferred\b|\bpreference\b|\bpfd\b|\bprd\b|\bperpetual\b"),
    ("unit", r"\bunits?\b"),
    ("warrant", r"\bwarrants?\b"),
    ("right", r"\brights?\b"),
    ("debt", r"\bnotes?\b|\bdebentures?\b|\bbonds?\b|\bdue (?:\w+ )?\d{4}\b"),
    (
        "structured_product",
        r"\bcorts\b|\bstrats\b|trust securities|corp backed|\btr (?:ctf|certs)\b",
    ),
    ("exchange_traded_note", r"\betns?\b|exchange[- ]traded"),
)
_EXCLUDED_PATTERNS = tuple(
    (category, re.compile(pattern, re.IGNORECASE))
    for category, pattern in _EXCLUDED_SECURITIES
)
# Partnership common units (e.g. "Common Units representing Limited Partner
# Interests") are a company's equity, unlike SPAC units.
_PARTNERSHIP_INTERESTS = re.compile(r"limited partner|partnership", re.IGNORECASE)

# Yahoo labels that differ from the Finviz labels already stored.
COUNTRY_LABELS = {"United States": "USA"}
SECTOR_LABELS = {"Financial Services": "Financial"}


def normalize_ticker(symbol):
    """Symbol directory and Yahoo use different class separators (BRK.B vs BRK-B)."""
    return str(symbol or "").upper().strip().replace(".", "-")


def classify_listing(name, exchange, etf, test_issue):
    """Return "common" or the reason this listing is excluded."""
    if test_issue == "Y":
        return "test_issue"
    if etf == "Y":
        return "etf"
    if exchange not in EXCHANGES:
        return "other_exchange"
    for category, pattern in _EXCLUDED_PATTERNS:
        if pattern.search(name):
            if category == "unit" and _PARTNERSHIP_INTERESTS.search(name):
                continue
            return category
    return "common"


def _listing_rows(nasdaq_text, other_text):
    """(symbol, name, exchange, etf, test_issue) from both symbol directory files."""
    for line in nasdaq_text.splitlines():
        parts = line.split("|")
        if len(parts) < 8 or parts[0] == "Symbol" or line.startswith("File Creation"):
            continue
        yield parts[0], parts[1], "Q", parts[6], parts[3]
    for line in other_text.splitlines():
        parts = line.split("|")
        if (
            len(parts) < 8
            or parts[0] == "ACT Symbol"
            or line.startswith("File Creation")
        ):
            continue
        yield parts[0], parts[1], parts[2], parts[4], parts[6]


def parse_listings(nasdaq_text, other_text):
    """Return (sorted common-stock tickers, Counter of classifications)."""
    breakdown = Counter()
    tickers = set()
    for symbol, name, exchange, etf, test_issue in _listing_rows(
        nasdaq_text, other_text
    ):
        if not symbol.strip():
            continue
        category = classify_listing(name, exchange, etf, test_issue)
        breakdown[category] += 1
        if category == "common":
            tickers.add(normalize_ticker(symbol))
    return sorted(tickers), breakdown


def load_universe(get=requests.get, sleep=time.sleep):
    """Common stocks from the Nasdaq Trader symbol directory (free, no API key)."""
    texts = []
    for url in (NASDAQ_LISTED_URL, OTHER_LISTED_URL):

        def fetch(url=url):
            response = get(url, timeout=30)
            response.raise_for_status()
            return response.text

        text = _with_retries(fetch, sleep, f"symbol directory {url}")
        if not text:
            raise RuntimeError(f"Symbol directory unavailable: {url}")
        texts.append(text)
    tickers, breakdown = parse_listings(*texts)
    excluded = {k: v for k, v in sorted(breakdown.items()) if k != "common"}
    logger.info(f"Universe common_stocks={len(tickers)} excluded={excluded}")
    return tickers, breakdown


def _status(exc):
    return getattr(getattr(exc, "response", None), "status_code", None)


def _is_rate_limited(exc):
    return isinstance(exc, YFRateLimitError) or _status(exc) == 429


def _with_retries(fn, sleep, what):
    """Call fn(); retry errors, pausing longer after a rate limit. None on failure."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == MAX_ATTEMPTS:
                logger.error(f"{what} failed: {type(exc).__name__}: {exc}")
                return None
            delay = RATE_LIMIT_PAUSE_SECONDS if _is_rate_limited(exc) else attempt
            logger.warning(
                f"{what} attempt={attempt} error={type(exc).__name__}; retry in {delay}s"
            )
            sleep(delay)
    return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def format_market_cap(value):
    """Finviz style: millions or billions, two decimals ("149.97M", "5100.81B")."""
    number = _number(value)
    if not number or number < 0:
        return "-"
    if number >= 1e9:
        return f"{number / 1e9:.2f}B"
    return f"{number / 1e6:.2f}M"


def format_pe(value):
    number = _number(value)
    if number is None or number <= 0:
        return "-"
    return f"{number:.2f}"


def format_price(value):
    number = _number(value)
    return None if number is None else round(number, 2)


def format_change(price, previous_close):
    """Finviz style: "5.31%", "-1.20%" (no plus sign)."""
    price, previous_close = _number(price), _number(previous_close)
    if price is None or not previous_close:
        return "-"
    return f"{(price - previous_close) / previous_close * 100:.2f}%"


def format_volume(value):
    number = _number(value)
    if number is None:
        return "-"
    return f"{int(round(number)):,}"


def clean_company(name):
    """Finviz drops commas and the trailing period ("Amazon.com, Inc." -> "Amazon.com Inc")."""
    text = " ".join(str(name or "").replace(",", "").split()).rstrip(".")
    return text or "-"


def _label(value, labels):
    text = str(value or "").strip()
    return labels.get(text, text) or "-"


def build_document(serial_number, ticker, quote):
    """Finviz-shaped document from one Yahoo quote. Profile fields default to "-"."""
    price = quote.get("regularMarketPrice")
    return {
        "serial_number": serial_number,
        "ticker": ticker,
        "company": clean_company(quote.get("longName") or quote.get("shortName")),
        "sector": "-",
        "industry": "-",
        "country": "-",
        "market_cap": format_market_cap(quote.get("marketCap")),
        "pe_ratio": format_pe(quote.get("trailingPE")),
        "price": format_price(price),
        "change": format_change(price, quote.get("regularMarketPreviousClose")),
        "volume": format_volume(quote.get("regularMarketVolume")),
    }


def _quote_fetcher():
    client = YfData()

    def fetch(symbols):
        raw = client.get_raw_json(
            QUOTE_URL,
            params={"symbols": ",".join(symbols), "formatted": "false"},
            timeout=10,
        )
        results = ((raw or {}).get("quoteResponse") or {}).get("result") or []
        return {normalize_ticker(q.get("symbol")): q for q in results}

    return fetch


def _profile_fetcher():
    client = YfData()

    def fetch(ticker):
        try:
            raw = client.get_raw_json(
                f"{PROFILE_URL}/{ticker}",
                params={"modules": "assetProfile,price", "formatted": "false"},
                timeout=10,
            )
        except Exception as exc:
            if _status(exc) == 404:
                return {}
            raise
        results = ((raw or {}).get("quoteSummary") or {}).get("result") or []
        if not results:
            return {}
        profile = results[0].get("assetProfile") or {}
        price = results[0].get("price") or {}
        return {
            "company": clean_company(price.get("longName") or price.get("shortName")),
            "sector": _label(profile.get("sector"), SECTOR_LABELS),
            "industry": _label(profile.get("industry"), {}),
            "country": _label(profile.get("country"), COUNTRY_LABELS),
        }

    return fetch


def fetch_quotes(tickers, fetch=None, sleep=time.sleep):
    """Return (quotes by ticker, tickers whose batch failed after retries)."""
    fetch = fetch or _quote_fetcher()
    quotes = {}
    failed = []
    for start in range(0, len(tickers), QUOTE_BATCH_SIZE):
        batch = tickers[start : start + QUOTE_BATCH_SIZE]
        got = _with_retries(
            lambda: fetch(batch), sleep, f"Quotes {batch[0]}..{batch[-1]}"
        )
        if got is None:
            failed.extend(batch)
        else:
            quotes.update(got)
    return quotes, failed


def fetch_profiles(tickers, fetch=None, sleep=time.sleep):
    """One profile per ticker, sequentially.

    The first rate limit pauses RATE_LIMIT_PAUSE_SECONDS; the next one stops
    the run. Returns (profiles by ticker, failed tickers, stopped).
    """
    fetch = fetch or _profile_fetcher()
    profiles = {}
    failed = []
    paused = False
    for index, ticker in enumerate(tickers, start=1):
        errors = 0
        while True:
            try:
                profiles[ticker] = fetch(ticker)
                break
            except Exception as exc:
                if _is_rate_limited(exc):
                    if paused:
                        remaining = len(tickers) - index + 1
                        logger.warning(
                            f"Rate limited again; stopping with {remaining} profiles left"
                        )
                        return profiles, failed, True
                    paused = True
                    logger.warning(
                        f"Rate limited; pausing {RATE_LIMIT_PAUSE_SECONDS}s once"
                    )
                    sleep(RATE_LIMIT_PAUSE_SECONDS)
                    continue
                errors += 1
                if errors == MAX_ATTEMPTS:
                    logger.warning(
                        f"Profile failed ticker={ticker} error={type(exc).__name__}: {exc}"
                    )
                    failed.append(ticker)
                    break
                sleep(errors)
        if index % 500 == 0:
            logger.info(f"Profiles {index}/{len(tickers)}")
    return profiles, failed, False


def run_daily(
    collection, max_workers, limit=None, universe=None, fetch=None, sleep=time.sleep
):
    """Quote every common stock and upsert price fields. Returns a summary dict."""
    tickers, breakdown = universe or load_universe()
    if limit:
        tickers = tickers[:limit]
    quotes, failed = fetch_quotes(tickers, fetch=fetch, sleep=sleep)
    failed_set = set(failed)

    invalid = []
    non_equity = []
    documents = []
    for ticker in tickers:
        if ticker in failed_set:
            continue
        quote = quotes.get(ticker)
        if quote is None:
            invalid.append(ticker)
        elif quote.get("quoteType") != "EQUITY":
            non_equity.append(ticker)
        else:
            documents.append(build_document(len(documents) + 1, ticker, quote))

    if invalid:
        logger.warning(f"No Yahoo quote for {len(invalid)} tickers: {invalid[:20]}")
    if non_equity:
        logger.info(f"Skipped {len(non_equity)} non-EQUITY quotes: {non_equity[:20]}")

    chunks = [
        documents[i : i + WRITE_CHUNK_SIZE]
        for i in range(0, len(documents), WRITE_CHUNK_SIZE)
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(
            executor.map(
                lambda chunk: write_or_update_to_mongo(
                    chunk, collection, insert_only=PROFILE_FIELDS
                ),
                chunks,
            )
        )

    return {
        "requested": len(tickers),
        "documents": len(documents),
        "invalid": invalid,
        "non_equity": non_equity,
        "failed": failed,
        "breakdown": breakdown,
    }


def run_weekly(collection, limit=None, universe=None, fetch=None, sleep=time.sleep):
    """Refresh profile fields for stored tickers, missing ones first."""
    tickers, _breakdown = universe or load_universe()
    if limit:
        tickers = tickers[:limit]
    stored = {
        doc["ticker"]: doc
        for doc in collection.find(
            {"ticker": {"$in": tickers}}, {"ticker": 1, "sector": 1}
        )
    }
    tickers = [t for t in tickers if t in stored]
    tickers.sort(key=lambda t: stored[t].get("sector") not in (None, "", "-"))
    missing = sum(1 for t in tickers if stored[t].get("sector") in (None, "", "-"))
    logger.info(f"Profiles to refresh={len(tickers)} missing_sector={missing}")

    profiles, failed, stopped = fetch_profiles(tickers, fetch=fetch, sleep=sleep)
    updated = update_profiles(profiles, collection)
    return {
        "requested": len(tickers),
        "fetched": len(profiles),
        "updated": updated,
        "failed": failed,
        "stopped": stopped,
    }
