"""
Stock data scraper main application.

This script fetches stock data from the Finviz website and stores it in MongoDB.
"""

import json
import os
import argparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient
from logging_config import get_logger
from stock_functions import get_data, check_if_trading_happened, reset_aggregate_counts, get_aggregate_counts

parser = argparse.ArgumentParser()
parser.add_argument("--env", help="Environment to run the script in")
args = parser.parse_args()

# Load config from JSON file
with open('config.json') as f:
    config_data = json.load(f)

if args.env:
    config = config_data[args.env]
else:
    config = config_data["dev"]
print(config)


# Get logger for this module
logger = get_logger(__name__)

load_dotenv()

db_username = os.getenv('DB_USERNAME')
db_password = os.getenv('DB_PASSWORD')




# MongoDB connection
CONNECTION_URI = f"mongodb+srv://{db_username}:{db_password}@stockycluster.qni7i.mongodb.net/myFirstDatabase?retryWrites=true&w=majority"
DB_NAME = config["DB_name"]
COLLECTION_NAME = config["collection_name"]

# Set up MongoDB connection
client = MongoClient(CONNECTION_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]


def main():

    trading1 = check_if_trading_happened(config["sample_stocks"][0], collection)
    trading2 = check_if_trading_happened(config["sample_stocks"][1], collection)
    if trading1 and trading2:
        logger.info("Both stocks are trading, starting data collection...")
    else:
        logger.info("One or both stocks are not trading, skipping data collection...")
        return

    """Main function to run the stock data scraper."""
    logger.info("Starting stock data scraping process")
    
    # Start multi-threaded scraping
    max_workers = config["max_workers"]
    logger.info(f"Starting multi-threaded data scraping with {max_workers} workers")
    
    reset_aggregate_counts()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Scrape data from pages 1 to 9501, stepping by 20
        executor.map(lambda start: get_data(start, collection), range(1, config["end_index"], 20))
    
    totals = get_aggregate_counts()
    logger.info(f"Done. read={totals['total_read']}, inserted={totals['inserted']}, updated={totals['updated']}")


if __name__ == "__main__":
    main() 