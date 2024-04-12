"""
Author: Gunit Bindal (https://upwork.com/freelancers/gunitb)
Author Email: thegbdevelopers@gmail.com

This script fetches stock data from the Finviz website and stores it in MongoDB.

Beginner's Instructions:
1. Download and install Python from https://www.python.org/downloads/
2. Install the required packages by running the following command in your terminal:
   `pip install -r requirements.txt`
3. Replace the `CONNECTION_URI`, `DB_NAME`, and `COLLECTION_NAME` constants with your MongoDB connection details.
4. Run the script using the following command:
   `python main.py`    
"""

import random
import requests
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient

# Constants for MongoDB connection
CONNECTION_URI = "mongodb+srv://amiros:AI6i7ZzZHgM5H5H0@stockycluster.qni7i.mongodb.net/myFirstDatabase?retryWrites=true&w=majority" # Your MongoDB connection URI
DB_NAME = "stock_data" # Your database name
COLLECTION_NAME = "stockss" # Your collection/ table name

# Set up MongoDB connection
client = MongoClient(CONNECTION_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

def was_there_trading():
    # collection.find_one({"serial_number": data["serial_number"]})
    msft_last_change = collection.find_one({"ticker": "MSFT"})["change"]
    msft_url = "https://finance.yahoo.com/quote/MSFT/history/?guccounter=1&guce_referrer=aHR0cHM6Ly93d3cuZ29vZ2xlLmNvbS8&guce_referrer_sig=AQAAAN6ZYIgRMxMyzJHXk0WqS7Fkss-h8M0_s1eQNN9xaNs8h01rFoFSbjiQaCoVEtxVSdN2ZZSHL0ueEoHyIctH7Ht4tPAv4O9PVlIP0c_GlUt7XPow8CeiAAq1e9FTqt9pNSNvhUrUDZ5c43KGNdilMLIg6NlvIqDvb7ZEQloAmQB7"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    
    response = requests.get(msft_url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    # # div = soup.find('div', class_='symbol-page-header__pricing-changes')["span"][1]
    # nasdaq_change = soup.select_one('span.symbol-page-header__pricing-percent')
    # print(nasdaq_change)

    # Find the element containing the current stock price
    price_element = soup.find("span", class_="e3b14781 ee3e99dd e59c8479")


    if price_element:
        current_price = price_element.get_text.strip()
        print("Current Price:", current_price)
    else:
        print("Failed to retrieve the current price.")
    

    if msft_last_change != 0.5:
        print("No activity today!")
        return False
    else:
        return True

def write_or_update_to_mongo(page_data):
    """
    Writes or updates stock information in MongoDB.
    
    This function deletes existing records with the same serial numbers from the database and inserts new ones.
    It handles the insertion in a bulk operation to optimize performance.
    
    Args:
        page_data (list): A list of dictionaries, each representing stock information.
    """
    # serial_numbers = [x['serial_number'] for x in page_data]
    
    # # Delete existing records
    # collection.delete_many({"serial_number": {"$in": serial_numbers}})
    
    # # Insert new records
    # collection.insert_many(page_data, ordered=False)
    
    # Update Records


    for data in page_data: #ADD ERROR handling in case "-" is part of the stock's data
        try:
            current_stock = collection.find_one({"serial_number": data["serial_number"]})
            if current_stock is not None:
                try:          
                    new_change = float(data["change"].strip("%"))
                    current_rising_days = 0 if current_stock["numOfRisingDays"] == "-" else int(current_stock["numOfRisingDays"])
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
                    print(f"Error fetching data row: {e}")
        except Exception as e:
            print(f"Error in making request to mongo: {e}")
            # else:
            #     print("Stock {} was not found in DB".format(data['serial_number']))        
    try:
        collection.update_one({"serial_number": data["serial_number"]}, {"$set": {
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
            "numOfRisingDays": "0" if rising_days is None else str(rising_days),
            "accumulatedChange": str(incremental_change)
            }}, upsert=True)
    except Exception as e:
            print(f"Error writing data row: {e}")
    print(f"Data written to MongoDB for page {page_data[0]['serial_number']} to {page_data[-1]['serial_number']}")


def get_data(start):
    """
    Fetches stock data from the Finviz website and stores it in MongoDB.
    
    This function constructs the URL based on the starting index, makes an HTTP GET request to retrieve the page,
    parses the HTML to extract stock information, and stores the data in MongoDB.
    
    Args:
        start (int): The starting index for stock data pagination.
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
        response = requests.get(url, proxies=proxies, headers=headers, timeout=1)
        while response.status_code != 200:
            response = requests.get(url, headers=headers)
    except Exception as e:
            print(f"Error making request: {e}")
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
            print(f"Error processing data row: {e}")
    
    if page_data:
        print(f"Retrieved data for {page_data[0]['serial_number']} to {page_data[-1]['serial_number']}")
        write_or_update_to_mongo(page_data)



def get_proxy_randomly():
    proxy_list = ['38.154.227.167:5868', '185.199.229.156:7492', '185.199.228.220:7300',
                '185.199.231.45:8382', '188.74.210.207:6286', '188.74.183.10:8279',
                '188.74.210.21:6100', '45.155.68.129:8133', '154.95.36.199:6893', 
                '45.94.47.66:8110'] 
    random_number = random.randint(0, 9)
    return proxy_list[random_number]



# Execute the data retrieval in a multi-threaded manner to improve efficiency
         
def main():  
    # if was_there_trading():             
    with ThreadPoolExecutor(max_workers=50) as executor:
        # executor.map(get_data, range(1, 9501, 20))
        executor.map(get_data, range(1, 1001, 20))
    executor.shutdown(wait=True)    

if __name__ == "__main__":
    main() 