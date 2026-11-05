"""
MongoDB writes for NASDAQ stock documents.
"""

import threading
from datetime import datetime, timezone

from logging_config import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Slow-changing fields. The daily run sets them only when a ticker is first
# inserted; the weekly run refreshes them with update_profiles.
PROFILE_FIELDS = ("company", "sector", "industry", "country")

# Thread-safe aggregate counters across the whole run
_aggregate_lock = threading.Lock()
_aggregate_counts = {
    "total_read": 0,
    "inserted": 0,
    "updated": 0,
}


def reset_aggregate_counts():
    with _aggregate_lock:
        _aggregate_counts["total_read"] = 0
        _aggregate_counts["inserted"] = 0
        _aggregate_counts["updated"] = 0


def get_aggregate_counts():
    with _aggregate_lock:
        return dict(_aggregate_counts)


def write_or_update_to_mongo(page_data, collection, insert_only=()):
    """
    Writes or updates stock information in MongoDB.

    This function uses atomic operations with optimistic locking and price-based duplicate detection
    to prevent race conditions and ensure rising_days is calculated correctly.

    Args:
        page_data (list): A list of dictionaries, each representing stock information.
        collection: MongoDB collection object for database operations.
        insert_only: Profile fields written only when the ticker is new ($setOnInsert).
    """
    inserted_count = 0
    updated_count = 0
    write_time = datetime.now(timezone.utc)

    for data in page_data:
        try:
            # Normalize ticker to uppercase for consistent matching (fixes case sensitivity issues)
            ticker = data["ticker"].upper().strip() if data.get("ticker") else None
            if not ticker:
                logger.warning(
                    f"Skipping record with missing or empty ticker: {data.get('serial_number', 'unknown')}"
                )
                continue

            profile = {
                field: data[field]
                for field in PROFILE_FIELDS
                if field not in insert_only
            }
            current_stock = collection.find_one({"ticker": ticker})

            if current_stock is not None:
                # Existing stock - check for duplicate and update with atomic operations
                try:
                    # Get current price from database
                    current_price = current_stock.get("price")
                    new_price = data.get("price")

                    # DUPLICATE DETECTION: Check if price actually changed
                    # If prices are the same (or very close), this is a duplicate - skip incrementing rising_days
                    price_unchanged = False
                    if current_price is not None and new_price is not None:
                        try:
                            current_price_float = float(current_price)
                            new_price_float = float(new_price)
                            # If prices are within 1 cent, consider them the same (handles rounding)
                            if abs(current_price_float - new_price_float) < 0.01:
                                price_unchanged = True
                        except (ValueError, TypeError):
                            # If price conversion fails, proceed with update
                            pass

                    if price_unchanged:
                        # Price hasn't changed - update other fields but DON'T increment rising_days
                        # This prevents duplicate processing from incrementing the counter multiple times
                        result = collection.update_one(
                            {"ticker": ticker},
                            {
                                "$set": {
                                    "serial_number": data["serial_number"],
                                    "ticker": ticker,
                                    **profile,
                                    "market_cap": data["market_cap"],
                                    "pe_ratio": data["pe_ratio"],
                                    "volume": data["volume"],
                                    "change": data["change"],
                                    "timestamp": write_time,
                                    # DON'T update price, numOfRisingDays, or accumulatedChange
                                }
                            },
                        )
                        if result.modified_count > 0:
                            updated_count += 1
                        continue

                    # Price changed - proceed with calculating new rising_days
                    # Get current state
                    current_rising_days_str = current_stock.get("numOfRisingDays", "-")
                    current_rising_days = (
                        0
                        if current_rising_days_str == "-"
                        else int(current_rising_days_str)
                    )

                    current_change_str = current_stock.get("accumulatedChange", "-")
                    current_change = (
                        0 if current_change_str == "-" else float(current_change_str)
                    )

                    # Calculate actual price change percentage from stored prices (more reliable than the reported change)
                    try:
                        current_price_float = float(current_price)
                        new_price_float = float(new_price)
                        if current_price_float > 0:
                            actual_price_change_pct = (
                                (new_price_float - current_price_float)
                                / current_price_float
                            ) * 100
                        else:
                            # Fallback to reported change if price is 0 or invalid
                            actual_price_change_pct = (
                                0
                                if data["change"] == "-"
                                else float(data["change"].strip("%"))
                            )
                    except (ValueError, TypeError, ZeroDivisionError):
                        # Fallback to reported change if price calculation fails
                        actual_price_change_pct = (
                            0
                            if data["change"] == "-"
                            else float(data["change"].strip("%"))
                        )

                    # Calculate new rising_days based on actual price change
                    if actual_price_change_pct > 0:
                        # Price increased
                        if current_rising_days < 0:
                            # Transition from falling to rising: reset to 1
                            new_rising_days = 1
                            new_accumulated_change = actual_price_change_pct
                        else:
                            # Continue rising: increment
                            new_rising_days = current_rising_days + 1
                            new_accumulated_change = (
                                current_change + actual_price_change_pct
                            )
                    elif actual_price_change_pct < 0:
                        # Price decreased
                        if current_rising_days > 0:
                            # Transition from rising to falling: reset to -1
                            new_rising_days = -1
                            new_accumulated_change = actual_price_change_pct
                        else:
                            # Continue falling: decrement
                            new_rising_days = current_rising_days - 1
                            new_accumulated_change = (
                                current_change + actual_price_change_pct
                            )
                    else:
                        # Price unchanged (shouldn't happen due to duplicate check above, but handle it)
                        new_rising_days = current_rising_days
                        new_accumulated_change = current_change

                    # ATOMIC UPDATE with optimistic locking: only update if rising_days hasn't changed
                    # This prevents race conditions when multiple threads process the same stock
                    result = collection.update_one(
                        {
                            "ticker": ticker,
                            "numOfRisingDays": current_rising_days_str,  # Only match if unchanged (optimistic lock)
                        },
                        {
                            "$set": {
                                "serial_number": data["serial_number"],
                                "ticker": ticker,
                                **profile,
                                "market_cap": data["market_cap"],
                                "pe_ratio": data["pe_ratio"],
                                "price": data["price"],
                                "change": data["change"],
                                "volume": data["volume"],
                                "numOfRisingDays": str(new_rising_days),
                                "accumulatedChange": str(new_accumulated_change),
                                "timestamp": write_time,
                            }
                        },
                    )

                    if result.modified_count > 0:
                        updated_count += 1
                    elif result.matched_count > 0:
                        # Matched but not modified - likely all fields were already set to these values
                        # This is fine, count as successful update (no-op)
                        updated_count += 1
                    else:
                        # Optimistic lock failed - rising_days changed between read and update (race condition)
                        # Another thread successfully updated it, so we skip this update
                        logger.warning(
                            f"Optimistic lock failed for ticker {ticker} - race condition detected, skipping update. This may indicate the stock needs manual review."
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing data for stock with ticker {ticker}: {e}",
                        exc_info=True,
                    )
                    continue
            else:
                # New stock - initialize values based on change percentage
                try:
                    # Get change percentage to determine initial rising/falling state
                    new_change = (
                        0 if data["change"] == "-" else float(data["change"].strip("%"))
                    )

                    if new_change > 0:
                        # Stock is rising on first day
                        initial_rising_days = 1
                        initial_accumulated_change = new_change
                    elif new_change < 0:
                        # Stock is falling on first day
                        initial_rising_days = -1
                        initial_accumulated_change = new_change
                    else:
                        # No change on first day
                        initial_rising_days = 0
                        initial_accumulated_change = 0
                except (ValueError, TypeError):
                    # If change parsing fails, default to 0
                    initial_rising_days = 0
                    initial_accumulated_change = 0

                update = {
                    "$set": {
                        "serial_number": data["serial_number"],
                        "ticker": ticker,
                        **profile,
                        "market_cap": data["market_cap"],
                        "pe_ratio": data["pe_ratio"],
                        "price": data["price"],
                        "change": data["change"],
                        "volume": data["volume"],
                        "numOfRisingDays": str(initial_rising_days),
                        "accumulatedChange": str(initial_accumulated_change),
                        "timestamp": write_time,
                    }
                }
                if insert_only:
                    update["$setOnInsert"] = {
                        field: data[field] for field in insert_only
                    }
                result = collection.update_one({"ticker": ticker}, update, upsert=True)
                if result.upserted_id is not None:
                    inserted_count += 1
                else:
                    updated_count += result.modified_count

        except Exception as e:
            ticker_str = (
                ticker if "ticker" in locals() else data.get("ticker", "unknown")
            )
            logger.error(
                f"Error making request to MongoDB for stock with ticker {ticker_str}: {e}",
                exc_info=True,
            )
            continue

    try:
        total_read = len(page_data)
    except Exception:
        total_read = 0

    # Update global aggregates
    with _aggregate_lock:
        _aggregate_counts["total_read"] += total_read
        _aggregate_counts["inserted"] += inserted_count
        _aggregate_counts["updated"] += updated_count

    # Per-page completion log without per-page totals
    logger.info(
        f"Upsert {page_data[0]['serial_number']}-{page_data[-1]['serial_number']}"
    )


def update_profiles(profiles, collection):
    """$set company, sector, industry, and country on existing documents.

    Missing values ("-", empty, None) are skipped so they never replace stored
    data. Tickers without a document are not inserted. Returns modified count.
    """
    updated = 0
    for ticker, profile in profiles.items():
        fields = {
            field: profile[field]
            for field in PROFILE_FIELDS
            if profile.get(field) not in (None, "", "-")
        }
        if not fields:
            continue
        try:
            result = collection.update_one({"ticker": ticker}, {"$set": fields})
        except Exception as e:
            logger.error(f"Profile update failed for ticker {ticker}: {e}")
            continue
        updated += result.modified_count
    return updated
