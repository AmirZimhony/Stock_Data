"""
NASDAQ stock scraper main application.

Fetches common-stock data from Yahoo Finance (yfinance) and stores it in MongoDB.
--mode daily updates price fields; --mode weekly refreshes company, sector,
industry, and country.
"""

import stocker_metrics

import config
from logging_config import get_logger
from stock_functions import get_aggregate_counts, reset_aggregate_counts
from yfinance_scraper import run_daily, run_weekly

args = config.parse_args()
config.configure(args)

logger = get_logger(__name__)


def daily():
    reset_aggregate_counts()
    summary = run_daily(
        config.collection,
        config.config["max_workers"],
        limit=config.config["limit"],
    )
    totals = get_aggregate_counts()
    logger.info(
        f"Daily summary requested={summary['requested']} "
        f"documents={summary['documents']} invalid={len(summary['invalid'])} "
        f"non_equity={len(summary['non_equity'])} failed={len(summary['failed'])} "
        f"inserted={totals['inserted']} updated={totals['updated']}"
    )

    if totals["total_read"] == 0:
        raise RuntimeError(f"No stock data scraped; failed={len(summary['failed'])}")
    if summary["failed"]:
        raise RuntimeError(
            f"Scrape incomplete: failed_tickers={len(summary['failed'])} "
            f"first={summary['failed'][:10]}"
        )

    stocker_metrics.gauge("stocks.read", totals["total_read"])
    stocker_metrics.gauge("stocks.inserted", totals["inserted"])
    stocker_metrics.gauge("stocks.updated", totals["updated"])


def weekly():
    summary = run_weekly(config.collection, limit=config.config["limit"])
    logger.info(
        f"Weekly summary requested={summary['requested']} "
        f"fetched={summary['fetched']} updated={summary['updated']} "
        f"failed={len(summary['failed'])} stopped={summary['stopped']}"
    )

    if summary["requested"] and not summary["fetched"]:
        raise RuntimeError("No profiles fetched")

    stocker_metrics.gauge("profiles.fetched", summary["fetched"])
    stocker_metrics.gauge("profiles.updated", summary["updated"])


def main():
    """Main function to run the stock data scraper."""
    mode = config.config["mode"]
    logger.info(
        f"Starting NASDAQ {mode} run env={config.active_env} "
        f"limit={config.config['limit'] or 'all'}"
    )
    if mode == "weekly":
        weekly()
    else:
        daily()


if __name__ == "__main__":
    main()
