"""
Stock data processing functions for fetching and storing stock information.
"""

import requests
import time
from bs4 import BeautifulSoup
import yfinance as yf
import threading
from logging_config import get_logger

# Get logger for this module
logger = get_logger(__name__)

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

def write_or_update_to_mongo(page_data, collection):
    """
    Writes or updates stock information in MongoDB.
    
    This function deletes existing records with the same serial numbers from the database and inserts new ones.
    It handles the insertion in a bulk operation to optimize performance.
    
    Args:
        page_data (list): A list of dictionaries, each representing stock information.
        collection: MongoDB collection object for database operations.
    """
    # serial_numbers = [x['serial_number'] for x in page_data]
    
    # # Delete existing records
    # collection.delete_many({"serial_number": {"$in": serial_numbers}})
    
    # # Insert new records
    # collection.insert_many(page_data, ordered=False)
    
    # Update Records

    inserted_count = 0
    updated_count = 0

    for data in page_data:   
        try:
            current_stock = collection.find_one({"serial_number": data["serial_number"]})
            if current_stock is not None:
                try:
                    # Handle the case where change is "-"
                    new_change = 0 if data["change"] == "-" else float(data["change"].strip("%"))
                    
                    # Handle the case where numOfRisingDays is "-"
                    current_rising_days = 0 if current_stock["numOfRisingDays"] == "-" else int(current_stock["numOfRisingDays"])
                    
                    # Handle the case where accumulatedChange is "-"
                    current_change = 0 if current_stock["accumulatedChange"] == "-" else float(current_stock["accumulatedChange"])
                    
                    if new_change > 0:
                        if current_rising_days < 0:
                            rising_days = 1
                            incremental_change = new_change
                        else:
                            rising_days = current_rising_days + 1
                            incremental_change = current_change + new_change
                    else:
                        if new_change < 0:
                            if current_rising_days > 0:
                                rising_days = -1
                                incremental_change = new_change
                            else:
                                rising_days = current_rising_days - 1
                                incremental_change = current_change + new_change
                        else:
                            rising_days = current_rising_days
                            incremental_change = current_change
                except Exception as e:
                    logger.error(f"Error processing data for stock with serial number {data['serial_number']}: {e}")
                    continue
            else:
            # If stock is not found in the DB, initialize values
                rising_days = 0
                incremental_change = 0   
            result = collection.update_one({"serial_number": data["serial_number"]}, {"$set": {
                "ticker": data["ticker"],
                "company": data["company"],
                "sector": data["sector"],
                "industry": data["industry"],
                "country": data["country"],
                "market_cap": data["market_cap"],
                "pe_ratio": data["pe_ratio"],
                "price": data["price"],
                "change": data["change"],
                "volume": data["volume"],
                "numOfRisingDays": str(rising_days),
                "accumulatedChange": str(incremental_change)
            }}, upsert=True)
            if result.upserted_id is not None:
                inserted_count += 1
            else:
                updated_count += result.modified_count
        except Exception as e:
            logger.error(f"Error making request to MongoDB for stock with serial number {data['serial_number']}: {e}")
        continue

        # try:
        #     collection.update_one({"serial_number": data["serial_number"]}, {"$set": {
        #         "ticker": data["ticker"],
        #         "company": data["company"],
        #         "sector": data["sector"],
        #         "industry": data["industry"],
        #         "country": data["country"],
        #         "market_cap": data["market_cap"],
        #         "pe_ratio": data["pe_ratio"],
        #         "price": data["price"],
        #         "change": data["change"],
        #         "volume": data["volume"],
        #         "accumulatedChange": str(incremental_change)
        #     }}, upsert=True)
        # except Exception as e:
        #     logger.error(f"Error updating MongoDB for stock with serial number {data['serial_number']}: {e}")
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
    logger.info(f"Upsert {page_data[0]['serial_number']}-{page_data[-1]['serial_number']}")


def get_data(start, collection):
    """
    Fetches stock data from the Finviz website and stores it in MongoDB.
    
    This function constructs the URL based on the starting index, makes an HTTP GET request to retrieve the page,
    parses the HTML to extract stock information, and stores the data in MongoDB.
    
    Args:
        start (int): The starting index for stock data pagination.
        collection: MongoDB collection object for database operations.
    """
    url = "https://finviz.com/screener.ashx?v=111" if start == 1 else f"https://finviz.com/screener.ashx?v=111&R={start}"
    
    # proxy_string = "http://qgzgcxvk:m5dkuqvxcnuy@"
    # proxy_string = "http://"
    # proxy_url = proxy_string + "38.170.189.191:9757"
    proxy_url= 'http://qgzgcxvk-rotate:m5dkuqvxcnuy@p.webshare.io:80'

    proxies = {
    'http': proxy_url,
    'https': proxy_url
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    time.sleep(1)

    try:
        response = requests.get(url, proxies=proxies, headers=headers, timeout=10)
        trial_count = 0
        while response.status_code != 200:
            if trial_count < 5:
                logger.warning(f"Error making request: {response.status_code}, retrying...")
                response = requests.get(url, proxies=proxies, headers=headers, timeout=10)
                trial_count += 1
            else:
                logger.error(f"Error making request more than 5 times: {response.status_code}")
                return
    except Exception as e:
            logger.error(f"Error making request: {e}")
            return
    soup = BeautifulSoup(response.text, 'html.parser')
    page_data = []
    table = soup.select_one("table.screener_table")
    rows = table.select("tr[valign='top']")
    for tr in rows:
        try:
            json_data = {
                'serial_number': int(tr.find_all('td')[0].get_text(strip=True)),
                'ticker': tr.find_all('td')[1].get_text(strip=True),
                'company': tr.find_all('td')[2].get_text(strip=True),
                'sector': tr.find_all('td')[3].get_text(strip=True),
                'industry': tr.find_all('td')[4].get_text(strip=True),
                'country': tr.find_all('td')[5].get_text(strip=True),
                'market_cap': tr.find_all('td')[6].get_text(strip=True),
                'pe_ratio': tr.find_all('td')[7].get_text(strip=True),
                'price': float(tr.find_all('td')[8].get_text(strip=True)) if tr.find_all('td')[8].get_text(strip=True).replace('.', '', 1).isdigit() else None,
                'change': tr.find_all('td')[9].get_text(strip=True),
                'volume': tr.find_all('td')[10].get_text(strip=True)
            }
            page_data.append(json_data)
        except Exception as e:
            logger.error(f"Error processing data row: {e}")
    
    if page_data:
        logger.info(f"Fetched {page_data[0]['serial_number']}-{page_data[-1]['serial_number']}")
        write_or_update_to_mongo(page_data, collection)
        
        # Aggressive memory cleanup
        page_data.clear()
        soup.decompose()  # Destroy BeautifulSoup tree
        del soup, table, rows, page_data
        
        # Force garbage collection
        import gc
        gc.collect()

def check_if_trading_happened(ticker, collection):

    # Get last price from yfinance
    yf_ticker = yf.Ticker(ticker)
    data = yf_ticker.history(period="1d")
    if data.empty:
        return False

    yf_last_price = data['Close'].iloc[-1]

    # Get last price from MongoDB
    last_doc = collection.find_one({'ticker': ticker}, sort=[('serial_number', -1)])
    if not last_doc or 'price' not in last_doc:
        # No data in DB, so treat as trading happened
        return True

    db_last_price = last_doc['price']
    yf_p2 = round(float(yf_last_price), 2)
    db_p2 = round(float(db_last_price), 2)
    logger.info(f"{ticker} prices - yf={yf_p2:.2f}, db={db_p2:.2f}")
    
        

    # Compare prices
    if yf_p2 == db_p2:
        return False  # No trading happened
    else:
        return True
