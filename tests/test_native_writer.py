"""The MongoDB write payload carries native numbers (DP-103)."""

from datetime import datetime, timezone

import bson
import pytest

import stock_functions as sf
import yfinance_scraper as ys
from test_yfinance_scraper import MemoryCollection, _freeze_now, quote

YESTERDAY = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)

NATIVE_TYPES = {
    "change": float,
    "volume": int,
    "numOfRisingDays": int,
    "accumulatedChange": float,
}


class RecordingCollection(MemoryCollection):
    """Keeps every update_one payload so tests can inspect what is sent to Mongo."""

    def __init__(self, docs=None):
        super().__init__(docs)
        self.updates = []

    def update_one(self, query, update, upsert=False):
        self.updates.append(update)
        return super().update_one(query, update, upsert=upsert)


def _assert_native(payload, expected=NATIVE_TYPES):
    for field, kind in expected.items():
        assert type(payload[field]) is kind, (field, payload[field])


def _roundtrip(payload):
    """What Mongo would store: encode with the real BSON codec and decode."""
    return bson.decode(bson.encode(payload))


def _stored(rising_days, accumulated, timestamp, price=100.0):
    return {
        "ticker": "AAPL",
        "price": price,
        "numOfRisingDays": rising_days,
        "accumulatedChange": accumulated,
        "timestamp": timestamp,
    }


def _document(price=110.0, **overrides):
    return ys.build_document(
        1, "AAPL", quote("AAPL", regularMarketPrice=price, **overrides)
    )


def test_insert_payload_types(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection()
    sf.write_or_update_to_mongo([_document(349.51)], collection)

    payload = collection.updates[0]["$set"]
    _assert_native(payload)
    assert payload["volume"] == 88_958_281
    assert payload["change"] == 5.31
    assert payload["numOfRisingDays"] == 1
    _assert_native(_roundtrip(payload))


def test_new_day_payload_types(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection([_stored("2", "4.0", YESTERDAY)])
    sf.write_or_update_to_mongo([_document(110.0)], collection)

    payload = collection.updates[0]["$set"]
    _assert_native(payload)
    assert payload["numOfRisingDays"] == 3
    assert payload["accumulatedChange"] == pytest.approx(14.0)
    _assert_native(_roundtrip(payload))


def test_same_day_payload_types(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection([_stored("2", "4.0", TODAY)])
    sf.write_or_update_to_mongo([_document(101.5)], collection)

    payload = collection.updates[0]["$set"]
    _assert_native(payload, {"change": float, "volume": int})
    # Same-day writes leave the streak fields out of the payload entirely.
    assert "numOfRisingDays" not in payload
    assert "accumulatedChange" not in payload


def test_payload_keys_are_unchanged(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection()
    sf.write_or_update_to_mongo([_document()], collection)
    assert set(collection.updates[0]["$set"]) == {
        "serial_number",
        "ticker",
        "company",
        "sector",
        "industry",
        "country",
        "market_cap",
        "pe_ratio",
        "price",
        "change",
        "volume",
        "numOfRisingDays",
        "accumulatedChange",
        "timestamp",
    }


def test_missing_values_are_null_and_zero_stays_zero(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection()
    missing = ys.build_document(
        1,
        "NONE",
        {"symbol": "NONE", "regularMarketPrice": 10.0},
    )
    zero = ys.build_document(
        2,
        "ZERO",
        quote(
            "ZERO",
            regularMarketPrice=100.0,
            regularMarketPreviousClose=100.0,
            regularMarketVolume=0,
        ),
    )
    sf.write_or_update_to_mongo([missing, zero], collection)

    none_doc = _roundtrip(collection.updates[0]["$set"])
    assert none_doc["change"] is None
    assert none_doc["volume"] is None
    zero_doc = _roundtrip(collection.updates[1]["$set"])
    assert zero_doc["change"] == 0.0 and type(zero_doc["change"]) is float
    assert zero_doc["volume"] == 0 and type(zero_doc["volume"]) is int


def test_legacy_string_records_are_written_as_numbers(monkeypatch):
    """legacy_finviz still hands the writer display strings."""
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection()
    record = _document()
    record.update({"change": "-1.20%", "volume": "88,958,281"})
    sf.write_or_update_to_mongo([record], collection)

    payload = collection.updates[0]["$set"]
    assert payload["change"] == -1.2
    assert payload["volume"] == 88_958_281
    _assert_native(payload)


# P1 streak rule on the first and second run of a trading day.


@pytest.mark.parametrize(
    "rising_days, accumulated",
    [("2", "4.0"), (2, 4.0)],
    ids=["legacy-strings", "native-numbers"],
)
def test_streak_advances_once_per_trading_day(monkeypatch, rising_days, accumulated):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection([_stored(rising_days, accumulated, YESTERDAY)])

    sf.write_or_update_to_mongo([_document(110.0)], collection)
    first = dict(collection.docs["AAPL"])
    assert first["numOfRisingDays"] == 3
    assert first["accumulatedChange"] == pytest.approx(14.0)
    assert first["timestamp"] == TODAY

    # Second run the same day, even with a further price move.
    sf.write_or_update_to_mongo([_document(120.0)], collection)
    second = collection.docs["AAPL"]
    assert second["numOfRisingDays"] == 3
    assert second["accumulatedChange"] == first["accumulatedChange"]
    assert second["price"] == 120.0


def test_quiet_day_records_the_day_without_moving_the_streak(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection([_stored("2", "4.0", YESTERDAY, price=110.0)])
    sf.write_or_update_to_mongo([_document(110.0)], collection)
    stored = collection.docs["AAPL"]
    assert stored["numOfRisingDays"] == 2
    assert stored["accumulatedChange"] == 4.0
    assert stored["timestamp"] == TODAY


def test_reversal_resets_a_string_valued_streak(monkeypatch):
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection([_stored("3", "6.0", YESTERDAY)])
    sf.write_or_update_to_mongo([_document(95.0)], collection)
    stored = collection.docs["AAPL"]
    assert stored["numOfRisingDays"] == -1
    assert stored["accumulatedChange"] == pytest.approx(-5.0)


def test_flat_first_day_insert_stores_a_numeric_zero_streak(monkeypatch):
    """int 0 keeps the standardized text "0", exactly as the string writer produced."""
    _freeze_now(monkeypatch, TODAY)
    collection = RecordingCollection()
    flat = ys.build_document(
        1,
        "FLAT",
        quote("FLAT", regularMarketPrice=100.0, regularMarketPreviousClose=100.0),
    )
    sf.write_or_update_to_mongo([flat], collection)
    payload = _roundtrip(collection.updates[0]["$set"])
    assert payload["numOfRisingDays"] == 0
    assert payload["accumulatedChange"] == 0
