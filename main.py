"""
Stock data scraper main application.

This script fetches stock data from the Finviz website and stores it in MongoDB.
"""

from concurrent.futures import ThreadPoolExecutor

import config
from logging_config import get_logger
from stock_functions import get_aggregate_counts, get_data, reset_aggregate_counts

args = config.parse_args()
config.configure(args)

logger = get_logger(__name__)


def main():
    """Main function to run the stock data scraper."""
    logger.info("Starting stock data scraping process")

    max_workers = config.config["max_workers"]
    logger.info(f"Starting multi-threaded data scraping with {max_workers} workers")

    reset_aggregate_counts()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(
            lambda start: get_data(start, config.collection),
            range(1, config.config["end_index"], 20),
        )

    totals = get_aggregate_counts()
    logger.info(
        f"Done. read={totals['total_read']}, inserted={totals['inserted']}, updated={totals['updated']}"
    )
    if totals["total_read"] == 0:
        raise RuntimeError("No stock data scraped")


if __name__ == "__main__":
    main()
