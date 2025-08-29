from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient
import os
from dotenv import load_dotenv
import argparse
import json
import logging
from stock_functions import get_data, write_or_update_to_mongo, check_if_trading_happened

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_scraper.log'),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

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
logger.info(f"Loaded config: {config}")




load_dotenv()

db_username = os.getenv('DB_USERNAME')
db_password = os.getenv('DB_PASSWORD')


# Constants for MongoDB connection
CONNECTION_URI = f"mongodb+srv://{db_username}:{db_password}@stockycluster.qni7i.mongodb.net/myFirstDatabase?retryWrites=true&w=majority" # Your MongoDB connection URI
DB_NAME = "stock_data" # Your database name
COLLECTION_NAME = "stocks" # Your collection/ table name

# Set up MongoDB connection with memory-efficient settings
client = MongoClient(CONNECTION_URI, maxPoolSize=10, minPoolSize=1)  # Limit connection pool
db = client[DB_NAME]
collection = db[COLLECTION_NAME]






# Execute the data retrieval in a multi-threaded manner to improve efficiency
         
def main():  
    logger.info("Starting stock data collection process...")
    logger.info("Checking trading status...")
    trading1 = check_if_trading_happened(config["sample_stocks"][0])
    trading2 = check_if_trading_happened(config["sample_stocks"][1])
    logger.info(f"AAPL trading: {trading1}")
    logger.info(f"MSFT trading: {trading2}")
    
    if trading1 and trading2:
        logger.info("Both stocks are trading, starting data collection...")
        with ThreadPoolExecutor(max_workers=20) as executor:  # Reduced from 50 to 10
            # Single batch processing - let ThreadPool handle the queue
            executor.map(lambda x: get_data(x, collection), range(1, config["end_index"], 20))
        executor.shutdown(wait=True)
        logger.info("Data collection completed successfully")
    else:
        logger.warning("No trading happened, skipping data retrieval")  

if __name__ == "__main__":
    main() 