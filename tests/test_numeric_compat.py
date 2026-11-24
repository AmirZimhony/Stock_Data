"""Stored documents and incoming records may hold legacy strings or native numbers."""

import math
from datetime import datetime, timezone

import pytest

import stock_functions as sf
from stock_functions import parse_int, parse_number
from test_yfinance_scraper import MemoryCollection, _freeze_now

YESTERDAY = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("5.31%", 5.31),
        ("-1.20%", -1.2),
        ("0.00%", 0.0),
        (5.31, 5.31),
        (-1.2, -1.2),
        (0, 0.0),
        (0.0, 0.0),
        ("88,958,281", 88958281.0),
        (88958281, 88958281.0),
        ("3", 3.0),
        ("-3", -3.0),
        (" 4.25 ", 4.25),
    ],
)
def test_parse_number_reads_strings_and_numbers(value, expected):
    assert parse_number(value) == expected


@pytest.mark.parametrize(
    "value", [None, "-", "", "  ", "abc", "%", True, float("nan"), float("inf")]
)
def test_parse_number_treats_missing_and_malformed_as_none(value):
    assert parse_number(value) is None


def test_zero_is_not_missing():
    assert parse_number("0") == 0.0
    assert parse_number(0) == 0.0
    assert parse_int("0") == 0
    assert parse_int(None) is None


def test_parse_int_rounds_to_an_int():
    assert parse_int("88,958,281") == 88958281
    assert parse_int(3.0) == 3
    assert isinstance(parse_int("3"), int)


def _record(change, volume):
    return {
        "serial_number": 1,
        "ticker": "AAPL",
        "company": "Apple Inc",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "USA",
        "market_cap": "5100.81B",
        "pe_ratio": "38.94",
        "price": 110.0,
        "change": change,
        "volume": volume,
    }


def _stored(rising_days, accumulated):
    return {
        "ticker": "AAPL",
        "price": 100.0,
        "numOfRisingDays": rising_days,
        "accumulatedChange": accumulated,
        "timestamp": YESTERDAY,
    }


def _write(monkeypatch, stored, record, now=TODAY):
    _freeze_now(monkeypatch, now)
    collection = MemoryCollection([stored])
    sf.write_or_update_to_mongo([record], collection)
    return collection.docs["AAPL"]


@pytest.mark.parametrize(
    "rising_days, accumulated, expected_days, expected_accumulated",
    [
        ("2", "4.0", 3, 14.0),
        (2, 4.0, 3, 14.0),
        ("-2", "-4.0", 1, 10.0),
        (-2, -4.0, 1, 10.0),
        ("-", "-", 1, 10.0),
        (0, 0, 1, 10.0),
    ],
)
def test_existing_streak_reads_legacy_and_native_values(
    monkeypatch, rising_days, accumulated, expected_days, expected_accumulated
):
    """The price rose 10%, so the streak advances from either stored type."""
    stored = _write(
        monkeypatch,
        _stored(rising_days, accumulated),
        _record("10.00%", "1,000"),
    )
    assert parse_int(stored["numOfRisingDays"]) == expected_days
    assert math.isclose(parse_number(stored["accumulatedChange"]), expected_accumulated)


def test_incoming_change_may_be_a_string_or_a_number(monkeypatch):
    """With a stored price of 0 the reported change is the fallback."""
    results = []
    for change in ("-2.50%", -2.5):
        stored = _stored("3", "4.0")
        stored["price"] = 0
        doc = _write(monkeypatch, stored, _record(change, "1,000"))
        results.append((doc["numOfRisingDays"], doc["accumulatedChange"]))
    assert results[0] == results[1]
    assert parse_int(results[0][0]) == -1


@pytest.mark.parametrize("change", ["-", None, "abc"])
def test_missing_incoming_change_counts_as_zero_on_a_new_ticker(change):
    collection = MemoryCollection()
    sf.write_or_update_to_mongo([_record(change, "1,000")], collection)
    stored = collection.docs["AAPL"]
    assert parse_int(stored["numOfRisingDays"]) == 0
    assert parse_number(stored["accumulatedChange"]) == 0
