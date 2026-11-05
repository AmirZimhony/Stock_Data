import logging
import threading
import time
from email.utils import formatdate

import pytest

import legacy_finviz as sf

SCREENER_HTML = (
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
PROXY = "http://user:s3cret-token@p.webshare.io:80"


class FakeResponse:
    def __init__(
        self,
        text,
        status_code=200,
        headers=None,
        url="https://finviz.com/screener.ashx",
    ):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url


class AdvancingClock:
    """Single-threaded clock: sleep moves time forward by exactly the delay."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class FakeClock:
    """Virtual clock for threads blocked in RequestPacer.acquire."""

    def __init__(self):
        self._cond = threading.Condition()
        self._now = 0.0
        self._active = 0
        self._deadlines = []

    def start_thread(self):
        with self._cond:
            self._active += 1

    def end_thread(self):
        with self._cond:
            self._active -= 1
            self._maybe_advance()

    def monotonic(self):
        with self._cond:
            return self._now

    def sleep(self, seconds):
        if seconds <= 0:
            return
        with self._cond:
            deadline = self._now + seconds
            self._deadlines.append(deadline)
            self._active -= 1
            try:
                while self._now < deadline:
                    self._maybe_advance()
                    if self._now < deadline:
                        self._cond.wait()
            finally:
                self._active += 1
                try:
                    self._deadlines.remove(deadline)
                except ValueError:
                    pass

    def _maybe_advance(self):
        if self._active == 0 and self._deadlines:
            nxt = min(self._deadlines)
            if nxt > self._now:
                self._now = nxt
                self._cond.notify_all()


def install_clock(monkeypatch):
    clock = AdvancingClock()
    monkeypatch.setattr(sf.time, "sleep", clock.sleep)
    monkeypatch.setattr(sf.time, "monotonic", clock.monotonic)
    return clock


def use_screener(monkeypatch, get):
    monkeypatch.setattr(sf.requests, "get", get)
    monkeypatch.setenv("nasdaq_scraping_url", "https://finviz.com/screener.ashx?v=111")
    monkeypatch.setenv("proxy_url", PROXY)


def _join(threads):
    for thread in threads:
        thread.join(timeout=2)
    assert not any(thread.is_alive() for thread in threads)


def test_pacer_spaces_concurrent_workers():
    clock = FakeClock()
    pacer = sf.RequestPacer(2, sleep=clock.sleep, monotonic=clock.monotonic)
    starts = []
    lock = threading.Lock()

    def run():
        clock.start_thread()
        try:
            assert pacer.acquire() is True
            with lock:
                starts.append(clock.monotonic())
        finally:
            clock.end_thread()

    threads = [threading.Thread(target=run, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    _join(threads)
    assert sorted(starts) == [0, 2, 4, 6]


def test_cooldown_is_shared_across_workers():
    clock = FakeClock()
    pacer = sf.RequestPacer(2, sleep=clock.sleep, monotonic=clock.monotonic)
    clock.start_thread()
    assert pacer.acquire() is True
    clock.end_thread()
    pacer.cooldown(10)

    starts = []
    lock = threading.Lock()

    def run():
        clock.start_thread()
        try:
            assert pacer.acquire() is True
            with lock:
                starts.append(clock.monotonic())
        finally:
            clock.end_thread()

    threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    _join(threads)
    assert sorted(starts) == [10, 12]


def test_acquire_returns_false_when_blocked():
    clock = AdvancingClock()
    blocked = {"on": False}
    pacer = sf.RequestPacer(
        5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        is_blocked=lambda: blocked["on"],
    )
    assert pacer.acquire() is True
    blocked["on"] = True
    assert pacer.acquire() is False
    assert clock.sleeps == []


def test_backoff_bounds_and_cap():
    assert sf.backoff_seconds(0, rng=lambda: 1) == 5
    assert sf.backoff_seconds(1, rng=lambda: 1) == 10
    assert sf.backoff_seconds(2, rng=lambda: 1) == 20
    assert sf.backoff_seconds(3, rng=lambda: 1) == 40
    assert sf.backoff_seconds(4, rng=lambda: 1) == 80
    assert sf.backoff_seconds(5, rng=lambda: 1) == 120
    assert sf.backoff_seconds(0, rng=lambda: 0) == 2.5
    for index in range(8):
        base = min(120, 5 * (2**index))
        delay = sf.backoff_seconds(index, rng=lambda: 0.3)
        assert base * 0.5 <= delay <= base


def test_connection_errors_use_backoff_without_logging_proxy(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    clock = install_clock(monkeypatch)
    monkeypatch.setattr(sf.random, "random", lambda: 1.0)
    calls = {"n": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["n"] += 1
        raise sf.requests.exceptions.ProxyError(
            "Cannot connect to proxy http://user:s3cret-token@p.webshare.io:80"
        )

    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is False
    assert calls["n"] == 5
    assert clock.sleeps == [5, 10, 20, 40]
    assert "s3cret-token" not in caplog.text
    assert "ProxyError" in caplog.text


def test_retry_waits_for_shared_limiter(monkeypatch):
    clock = install_clock(monkeypatch)
    monkeypatch.setenv("SCRAPE_REQUEST_INTERVAL_SECONDS", "10")
    monkeypatch.setattr(sf.random, "random", lambda: 0.0)
    sf.reset_scrape_state()
    starts = []

    def fake_get(url, proxies=None, headers=None, timeout=None):
        starts.append(clock.monotonic())
        if len(starts) == 1:
            return FakeResponse("", 500)
        return FakeResponse(SCREENER_HTML, 200)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", lambda *_: None)
    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is True
    assert starts == [0, 10]
    assert clock.sleeps == [2.5, 7.5]


def test_429_honors_retry_after_seconds(monkeypatch):
    clock = install_clock(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse("", 429, headers={"Retry-After": "17"})
        return FakeResponse(SCREENER_HTML, 200)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", lambda *_: None)
    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is True
    assert calls["n"] == 2
    assert clock.sleeps == [17]


def test_429_honors_retry_after_http_date(monkeypatch):
    clock = install_clock(monkeypatch)
    when = formatdate(time.time() + 30, usegmt=True)
    calls = {"n": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse("", 429, headers={"Retry-After": when})
        return FakeResponse(SCREENER_HTML, 200)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", lambda *_: None)
    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is True
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(30, abs=1)


@pytest.mark.parametrize("header", [None, "not-a-date"])
def test_429_without_retry_after_uses_backoff(monkeypatch, header):
    clock = install_clock(monkeypatch)
    monkeypatch.setattr(sf.random, "random", lambda: 1.0)
    calls = {"n": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            headers_out = {} if header is None else {"Retry-After": header}
            return FakeResponse("", 429, headers=headers_out)
        return FakeResponse(SCREENER_HTML, 200)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", lambda *_: None)
    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is True
    assert clock.sleeps == [5]


def test_403_opens_breaker_without_retry(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls = {"n": 0}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        calls["n"] += 1
        assert "s3cret-token" in proxies["http"]
        return FakeResponse(
            "Attention Required Cloudflare " + ("A" * 400) + "TAIL_MARKER",
            403,
            headers={
                "Server": "cloudflare",
                "CF-Ray": "ray-123",
                "Set-Cookie": "session=s3cret-token",
                "X-Secret": "s3cret-token",
            },
            url="https://user:s3cret-token@finviz.com/screener.ashx",
        )

    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is False
    assert sf.get_data(21, None) is False
    assert calls["n"] == 1
    assert sf._breaker.is_open()
    assert caplog.text.count("HTTP 403 access restriction") == 1
    assert "https://finviz.com" in caplog.text
    assert "cloudflare" in caplog.text
    assert "ray-123" in caplog.text
    assert "Attention Required" in caplog.text
    assert "s3cret-token" not in caplog.text
    assert "TAIL_MARKER" not in caplog.text
    assert "Set-Cookie" not in caplog.text


def test_successful_page_preserves_parse_and_proxy(monkeypatch):
    seen = {}

    def fake_get(url, proxies=None, headers=None, timeout=None):
        seen["url"] = url
        seen["proxies"] = proxies
        seen["headers"] = headers
        seen["timeout"] = timeout
        return FakeResponse(SCREENER_HTML, 200)

    written = {}

    def fake_write(page_data, collection):
        written["rows"] = list(page_data)

    monkeypatch.setattr(sf, "write_or_update_to_mongo", fake_write)
    use_screener(monkeypatch, fake_get)
    assert sf.get_data(1, None) is True
    assert seen["url"] == "https://finviz.com/screener.ashx?v=111"
    assert seen["proxies"] == {"http": PROXY, "https": PROXY}
    assert seen["timeout"] == (sf.CONNECT_TIMEOUT, sf.READ_TIMEOUT)
    assert seen["timeout"] == (10, 30)
    assert seen["headers"]["Accept"].startswith("text/html")
    assert seen["headers"]["Accept-Language"] == "en-US,en;q=0.9"
    assert "Chrome/121" in seen["headers"]["User-Agent"]
    assert "sec-ch-ua" not in {key.lower() for key in seen["headers"]}
    assert written["rows"][0]["ticker"] == "AAPL"
    assert written["rows"][0]["price"] == 200.50


def test_interval_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("SCRAPE_REQUEST_INTERVAL_SECONDS", raising=False)
    sf.reset_scrape_state()
    assert sf._pacer.interval == 2

    monkeypatch.setenv("SCRAPE_REQUEST_INTERVAL_SECONDS", "0.5")
    sf.reset_scrape_state()
    assert sf._pacer.interval == 0.5


def test_worker_exception_propagates(monkeypatch):
    def fake(start, collection):
        if start == 41:
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(sf, "get_data", fake)
    with pytest.raises(RuntimeError, match="^boom$"):
        sf.run(None, 2, 101)


def test_partial_scrape_fails_the_run(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    offsets = list(range(1, 101, 20))
    monkeypatch.setattr(sf, "get_data", lambda start, collection: start != 21)
    monkeypatch.setattr(
        sf,
        "get_aggregate_counts",
        lambda: {"total_read": 20, "inserted": 1, "updated": 0},
    )
    with pytest.raises(RuntimeError, match=r"Scrape incomplete: failed_offsets=\[21\]"):
        sf.run(None, 2, 101)
    assert f"successful_pages={len(offsets) - 1}" in caplog.text
    assert "failed_pages=1" in caplog.text
    assert "stocks=20" in caplog.text
    assert "coverage=" in caplog.text


def test_complete_scrape_succeeds(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    offsets = list(range(1, 101, 20))
    monkeypatch.setattr(sf, "get_data", lambda *_: True)
    monkeypatch.setattr(
        sf,
        "get_aggregate_counts",
        lambda: {"total_read": 20, "inserted": 1, "updated": 19},
    )
    sf.run(None, 2, 101)
    assert f"successful_pages={len(offsets)}" in caplog.text
    assert "failed_pages=0" in caplog.text
    assert "coverage=100.0%" in caplog.text
