"""Mocked tests for the legacy Finviz scraper (legacy_finviz.py)."""

import pytest

import legacy_finviz as sf


def test_run_fails_when_nothing_scraped(monkeypatch):
    monkeypatch.setattr(sf, "get_data", lambda *_: True)
    monkeypatch.setattr(
        sf,
        "get_aggregate_counts",
        lambda: {"total_read": 0, "inserted": 0, "updated": 0},
    )
    with pytest.raises(RuntimeError, match="No stock data scraped"):
        sf.run(None, 2, 101)


def test_run_succeeds_when_data_scraped(monkeypatch):
    monkeypatch.setattr(sf, "get_data", lambda *_: True)
    monkeypatch.setattr(
        sf,
        "get_aggregate_counts",
        lambda: {"total_read": 20, "inserted": 1, "updated": 19},
    )
    assert sf.run(None, 2, 101)["total_read"] == 20


def test_get_data_parses_and_invokes_write(monkeypatch):
    # Header row includes a "Flag" column (as the data source added) to verify
    # it's ignored and the remaining fields still line up correctly by header
    # name. The ticker cell mimics the data source's real markup: a
    # company-logo <img> whose accessibility text repeats the ticker, plus the
    # visible tab-link anchor.
    html = (
        "<table class='screener_table'>"
        "<tr valign='middle'>"
        "<th>No.</th><th>Ticker</th><th>Company</th><th>Sector</th>"
        "<th>Industry</th><th>Country</th><th>Market Cap</th><th>P/E</th>"
        "<th>Price</th><th>Change %</th><th>Volume</th><th>Flag</th>"
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
        assert proxies == {
            "http": "http://proxy.example:80",
            "https": "http://proxy.example:80",
        }
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

    assert sf.get_data(1, None) is True

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


def test_get_data_parses_fv_table(monkeypatch):
    html = (
        "<html><body>"
        "<div class='fv-table_row' data-row-key='AAPL'>"
        "<div class='fv-table_cell' data-column-id='row'>1</div>"
        "<div class='fv-table_cell' data-column-id='ticker' data-ticker='AAPL'>"
        "<a class='fv-table_link'>AAPLAAPL</a>"
        "</div>"
        "<div class='fv-table_cell' data-column-id='company'>Apple Inc.</div>"
        "<div class='fv-table_cell' data-column-id='sector'>Technology</div>"
        "<div class='fv-table_cell' data-column-id='industry'>Consumer Electronics</div>"
        "<div class='fv-table_cell' data-column-id='country'>USA</div>"
        "<div class='fv-table_cell' data-column-id='marketCap'>3.0T</div>"
        "<div class='fv-table_cell' data-column-id='PE'>30.0</div>"
        "<div class='fv-table_cell' data-column-id='price'>200.50</div>"
        "<div class='fv-table_cell' data-column-id='change'>+1.23%</div>"
        "<div class='fv-table_cell' data-column-id='volume'>50,000,000</div>"
        "</div>"
        "</body></html>"
    )

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    called = {"data": None}

    def fake_write(page_data, collection):
        called["data"] = list(page_data)

    monkeypatch.setattr(sf.requests, "get", lambda *a, **k: FakeResponse(html, 200))
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    assert sf.get_data(1, None) is True

    assert called["data"] is not None
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


def test_get_data_uses_lowercase_r_for_pagination(monkeypatch):
    seen = {"url": None}

    class FakeResponse:
        def __init__(self):
            self.text = "<html><body>no table</body></html>"
            self.status_code = 200

    def fake_get(url, proxies=None, headers=None, timeout=None):
        seen["url"] = url
        return FakeResponse()

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    sf.get_data(21, None)

    assert seen["url"] == "https://example.com/screener?v=111&r=21"


def test_get_data_skips_write_on_unexpected_page(monkeypatch):
    """Simulates a blocked/changed response (no screener table) and expects a safe no-op."""

    class FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    def fake_get(url, proxies=None, headers=None, timeout=None):
        return FakeResponse(
            "<html><body>Access to this page has been denied</body></html>", 200
        )

    invoked = {"called": False}

    def fake_write(page_data, collection):
        invoked["called"] = True

    monkeypatch.setattr(sf.requests, "get", fake_get)
    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    monkeypatch.setenv("nasdaq_scraping_url", "https://example.com/screener?v=111")
    monkeypatch.setenv("proxy_url", "http://proxy.example:80")

    assert sf.get_data(1, None) is False

    assert invoked["called"] is False


def test_get_data_retries_after_request_exception(monkeypatch):
    """A transient error (e.g. ProxyError) should be retried, not abort immediately."""
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

    assert sf.get_data(1, None) is True

    assert calls["count"] == 3, "expected 2 failures then a successful 3rd attempt"
    assert called["data"] is not None, (
        "should have recovered and written data after retrying"
    )
    assert called["data"][0]["ticker"] == "AAPL"


def test_get_data_gives_up_after_repeated_exceptions(monkeypatch):
    """If every attempt raises, get_data should stop after 5 tries and not crash."""
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

    assert sf.get_data(1, None) is False

    assert calls["count"] == 5, "expected 5 attempts"
    assert invoked["called"] is False
