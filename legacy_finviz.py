"""
Legacy Finviz screener scraper, replaced by yfinance_scraper.py (DP-102).

Not on the active execution path. Kept for reference and rollback: run(...)
is the former main.py loop. It needs the nasdaq_scraping_url and proxy_url
environment variables.
"""

import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from logging_config import get_logger
from stock_functions import (
    get_aggregate_counts,
    reset_aggregate_counts,
    write_or_update_to_mongo,
)

# Get logger for this module
logger = get_logger(__name__)

# Shared by every worker. Defaults: one request each 2s, 5 attempts, 5s backoff.
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_ATTEMPTS = 5
BACKOFF_INITIAL = 5
BACKOFF_MULTIPLIER = 2
BACKOFF_MAX = 120
_DIAGNOSTIC_HEADERS = frozenset(
    {
        "server",
        "content-type",
        "cf-ray",
        "cf-mitigated",
        "via",
        "x-cache",
        "retry-after",
    }
)
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_USERINFO = re.compile(r"://[^/\s:@]+:[^/\s@]+@")

_pacer = None
_breaker = None
_page_lock = threading.Lock()
_successful_offsets = []
_failed_offsets = []


def _request_interval():
    raw = os.getenv("SCRAPE_REQUEST_INTERVAL_SECONDS", "2")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 2.0


def backoff_seconds(retry_index, rng=None):
    """Backoff for retry_index 0, 1, ... with jitter in [0.5, 1.0] of the base delay."""
    if rng is None:
        rng = random.random
    base = min(BACKOFF_MAX, BACKOFF_INITIAL * (BACKOFF_MULTIPLIER**retry_index))
    return base * (0.5 + 0.5 * rng())


class CircuitBreaker:
    """Stops new requests after the source denies access."""

    def __init__(self):
        self._lock = threading.Lock()
        self._open = False
        self.reason = None

    def is_open(self):
        with self._lock:
            return self._open

    def trip(self, reason):
        """Open the breaker. Return True only for the call that opened it."""
        with self._lock:
            if self._open:
                return False
            self._open = True
            self.reason = reason
            return True


class RequestPacer:
    """Thread-safe gate so request starts are at least `interval` seconds apart."""

    def __init__(self, interval, sleep=None, monotonic=None, is_blocked=None):
        self.interval = interval
        self._sleep = sleep
        self._monotonic = monotonic
        self._is_blocked = is_blocked or (lambda: False)
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._cooldown_until = 0.0

    def _now(self):
        if self._monotonic is not None:
            return self._monotonic()
        return time.monotonic()

    def _wait(self, delay):
        if delay <= 0:
            return
        if self._sleep is not None:
            self._sleep(delay)
        else:
            time.sleep(delay)

    def acquire(self):
        """Block until this caller may send. Return False if the breaker is open."""
        while True:
            with self._lock:
                if self._is_blocked():
                    return False
                now = self._now()
                earliest = max(self._next_slot, self._cooldown_until)
                if now >= earliest:
                    self._next_slot = now + self.interval
                    return True
                delay = earliest - now
            self._wait(delay)

    def cooldown(self, seconds):
        """Hold every worker until `seconds` from now (shared 429 pause)."""
        if seconds <= 0:
            return
        with self._lock:
            until = self._now() + seconds
            if until > self._cooldown_until:
                self._cooldown_until = until


def reset_scrape_state():
    """Clear the shared pacer, breaker, and page counters for a new run."""
    global _pacer, _breaker
    _breaker = CircuitBreaker()
    _pacer = RequestPacer(
        _request_interval(),
        is_blocked=lambda: _breaker.is_open(),
    )
    with _page_lock:
        _successful_offsets.clear()
        _failed_offsets.clear()


def get_page_results():
    with _page_lock:
        return {
            "successful": list(_successful_offsets),
            "failed": list(_failed_offsets),
        }


def _ensure_scrape_state():
    if _pacer is None or _breaker is None:
        reset_scrape_state()


def _record_success(offset):
    with _page_lock:
        _successful_offsets.append(offset)


def _record_failure(offset):
    with _page_lock:
        _failed_offsets.append(offset)


def _header(response, name):
    headers = getattr(response, "headers", None) or {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return value
    return None


def _origin(url):
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.hostname:
        return "unknown"
    return f"{parsed.scheme}://{parsed.hostname}"


def _redact(text):
    return _USERINFO.sub("://", text or "")


def _retry_after_seconds(response):
    raw = _header(response, "Retry-After")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def _diagnostic_headers(response):
    headers = getattr(response, "headers", None) or {}
    kept = {}
    for key, value in headers.items():
        if str(key).lower() in _DIAGNOSTIC_HEADERS:
            kept[str(key).lower()] = value
    return kept


def _log_access_restricted(offset, response, duration):
    snippet = " ".join((getattr(response, "text", "") or "")[:2000].split())[:300]
    logger.error(
        f"HTTP 403 access restriction offset={offset} status=403 "
        f"duration={duration:.2f}s origin={_origin(getattr(response, 'url', ''))} "
        f"headers={_diagnostic_headers(response)} body={_redact(snippet)}"
    )


def _log_failure(offset, attempt, duration, status, error_name):
    logger.error(
        f"Request failed offset={offset} status={status} attempt={attempt} "
        f"duration={duration:.2f}s error={error_name}"
    )


def _log_retry(offset, attempt, duration, status, delay, error_name):
    logger.warning(
        f"Retrying offset={offset} status={status} attempt={attempt} "
        f"duration={duration:.2f}s backoff={delay:.2f}s error={error_name}"
    )


def _fetch_page(url, proxies, offset):
    """GET one screener page. Return (response, duration) or None."""
    _ensure_scrape_state()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not _pacer.acquire():
            logger.debug(f"Circuit breaker open; skipping offset={offset}")
            return None
        started = time.monotonic()
        try:
            response = requests.get(
                url,
                proxies=proxies,
                headers=_REQUEST_HEADERS,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
        except requests.RequestException as exc:
            duration = time.monotonic() - started
            error_name = type(exc).__name__
            if attempt >= MAX_ATTEMPTS:
                _log_failure(offset, attempt, duration, "none", error_name)
                return None
            delay = backoff_seconds(attempt - 1)
            _log_retry(offset, attempt, duration, "none", delay, error_name)
            time.sleep(delay)
            continue

        duration = time.monotonic() - started
        status = response.status_code
        if status == 200:
            return response, duration
        if status == 403:
            if _breaker.trip(f"HTTP 403 offset={offset}"):
                _log_access_restricted(offset, response, duration)
            return None
        if status == 429:
            retry_after = _retry_after_seconds(response)
            delay = backoff_seconds(attempt - 1) if retry_after is None else retry_after
            _pacer.cooldown(delay)
            if attempt >= MAX_ATTEMPTS:
                _log_failure(offset, attempt, duration, status, "rate_limited")
                return None
            _log_retry(offset, attempt, duration, status, delay, "rate_limited")
            continue
        if 500 <= status < 600:
            if attempt >= MAX_ATTEMPTS:
                _log_failure(offset, attempt, duration, status, "server_error")
                return None
            delay = backoff_seconds(attempt - 1)
            _log_retry(offset, attempt, duration, status, delay, "server_error")
            time.sleep(delay)
            continue
        _log_failure(offset, attempt, duration, status, "http_error")
        return None
    return None


# Maps data-source screener header text (lowercased) to our output field names.
# Any other header (e.g. a new "Flag" column) is looked up here, found missing,
# and therefore ignored automatically - regardless of where it sits in the row.
_SCREENER_COLUMNS = {
    "no.": "serial_number",
    "ticker": "ticker",
    "company": "company",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "market cap": "market_cap",
    "p/e": "pe_ratio",
    "price": "price",
    "change": "change",
    "change %": "change",
    "volume": "volume",
}

# data-column-id on the current Finviz fv-table cells.
_FV_COLUMNS = {
    "row": "serial_number",
    "ticker": "ticker",
    "company": "company",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "marketCap": "market_cap",
    "PE": "pe_ratio",
    "price": "price",
    "change": "change",
    "volume": "volume",
}


def _map_columns(table):
    """Map known field names to their td index using the table's header row."""
    header_cells = table.find("tr").find_all(["th", "td"])
    columns = {}
    for i, cell in enumerate(header_cells):
        field = _SCREENER_COLUMNS.get(cell.get_text(strip=True).lower())
        if field:
            columns[field] = i
    return columns


def _cell_text(td):
    """Visible text for a screener cell.

    The ticker cell embeds a company-logo image whose accessibility text
    repeats the ticker (e.g. "A" + "A" -> "AA"); prefer the visible
    tab-link anchor when present to avoid that duplication.
    """
    link = td.find("a", class_="tab-link")
    return link.get_text(strip=True) if link else td.get_text(strip=True)


def _stock_from_display_fields(fields):
    """Build a stock dict from Finviz display strings (same shapes as before)."""
    price_text = fields["price"]
    return {
        "serial_number": int(fields["serial_number"]),
        "ticker": fields["ticker"],
        "company": fields["company"],
        "sector": fields["sector"],
        "industry": fields["industry"],
        "country": fields["country"],
        "market_cap": fields["market_cap"],
        "pe_ratio": fields["pe_ratio"],
        "price": float(price_text)
        if price_text.replace(".", "", 1).isdigit()
        else None,
        "change": fields["change"],
        "volume": fields["volume"],
    }


def _fv_cell_text(cell, column_id):
    if column_id == "ticker":
        ticker = (cell.get("data-ticker") or "").strip()
        if ticker:
            return ticker
    return cell.get_text(strip=True)


def _rows_from_fv_table(soup):
    """Parse current Finviz fv-table rows using visible cell text.

    None means this page has no fv-table (try the legacy HTML table).
    """
    rows = soup.select(".fv-table_row")
    if not rows:
        return None

    page_data = []
    for row in rows:
        try:
            cells = {
                cell.get("data-column-id"): cell
                for cell in row.select(".fv-table_cell")
                if cell.get("data-column-id")
            }
            missing = [
                name for col_id, name in _FV_COLUMNS.items() if col_id not in cells
            ]
            if missing:
                logger.error(
                    f"Finviz screener columns changed; missing expected fields: {sorted(missing)}"
                )
                return []
            fields = {
                name: _fv_cell_text(cells[col_id], col_id)
                for col_id, name in _FV_COLUMNS.items()
            }
            page_data.append(_stock_from_display_fields(fields))
        except Exception as e:
            logger.error(f"Error processing data row: {e}")
    if not page_data:
        logger.error("Finviz screener table has no data rows; unexpected page returned")
    return page_data


def _rows_from_html_table(soup):
    """Parse the legacy <table class='screener_table'> markup."""
    table = soup.select_one("table.screener_table")
    if table is None:
        logger.error(
            "Finviz screener table not found; unexpected page returned (blocked or layout changed?)"
        )
        return []

    columns = _map_columns(table)
    missing = set(_SCREENER_COLUMNS.values()) - set(columns)
    if missing:
        logger.error(
            f"Finviz screener columns changed; missing expected fields: {sorted(missing)}"
        )
        return []

    rows = table.select("tr[valign='top']")
    if not rows:
        logger.error("Finviz screener table has no data rows; unexpected page returned")
        return []

    page_data = []
    for tr in rows:
        try:
            tds = tr.find_all("td")
            fields = {name: _cell_text(tds[columns[name]]) for name in columns}
            page_data.append(_stock_from_display_fields(fields))
        except Exception as e:
            logger.error(f"Error processing data row: {e}")
    return page_data


def get_data(start, collection):
    """
    Fetches stock data from the configured screener data source and stores it in MongoDB.

    Base URL from nasdaq_scraping_url; for start > 1 appends &r={start} (or ?r=).
    proxy_url required. Parses HTML and stores rows in MongoDB.

    Returns True when rows were stored, False when this page failed.
    """
    _ensure_scrape_state()
    if _breaker.is_open():
        _record_failure(start)
        logger.debug(f"Circuit breaker open; skipping offset={start}")
        return False

    base = os.getenv("nasdaq_scraping_url")
    if not base:
        raise ValueError("nasdaq_scraping_url environment variable is required")

    proxy_url = os.getenv("proxy_url")
    if not proxy_url:
        raise ValueError("proxy_url environment variable is required")

    if start == 1:
        url = base
    else:
        sep = "&" if "?" in base else "?"
        url = f"{base}{sep}r={start}"

    proxies = {"http": proxy_url, "https": proxy_url}
    fetched = _fetch_page(url, proxies, start)
    if fetched is None:
        _record_failure(start)
        return False
    response, duration = fetched

    soup = BeautifulSoup(response.text, "html.parser")
    page_data = _rows_from_fv_table(soup)
    if page_data is None:
        page_data = _rows_from_html_table(soup)

    if page_data:
        logger.info(
            f"Fetched offset={start} status=200 duration={duration:.2f}s "
            f"serial={page_data[0]['serial_number']}-{page_data[-1]['serial_number']}"
        )
        write_or_update_to_mongo(page_data, collection)
        _record_success(start)
        page_data.clear()
        soup.decompose()
        import gc

        gc.collect()
        return True

    logger.warning(
        f"Page had no rows offset={start} status=200 duration={duration:.2f}s"
    )
    _record_failure(start)
    return False


def _scrape_stats(offsets, results):
    totals = get_aggregate_counts()
    scheduled = len(offsets)
    if len(results) == scheduled:
        failed = sorted(offset for offset, ok in zip(offsets, results) if not ok)
        successful = scheduled - len(failed)
    else:
        pages = get_page_results()
        failed = sorted(pages["failed"])
        successful = len(pages["successful"])
    coverage = (100.0 * successful / scheduled) if scheduled else 0.0
    return successful, failed, totals, coverage


def run(collection, max_workers, end_index):
    """Former main.py loop: scrape Finviz pages 1..end_index into collection.

    Returns aggregate counts. Raises RuntimeError on an empty or partial scrape.
    """
    logger.info(f"Starting multi-threaded data scraping with {max_workers} workers")

    reset_aggregate_counts()
    reset_scrape_state()

    offsets = list(range(1, end_index, 20))
    results = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(
                executor.map(lambda start: get_data(start, collection), offsets)
            )
    finally:
        successful, failed_offsets, totals, coverage = _scrape_stats(offsets, results)
        logger.info(
            f"Scrape summary successful_pages={successful} "
            f"failed_pages={len(failed_offsets)} stocks={totals['total_read']} "
            f"inserted={totals['inserted']} updated={totals['updated']} "
            f"coverage={coverage:.1f}%"
        )

    if totals["total_read"] == 0:
        raise RuntimeError(f"No stock data scraped; failed_offsets={failed_offsets}")
    if failed_offsets:
        raise RuntimeError(f"Scrape incomplete: failed_offsets={failed_offsets}")
    return totals
