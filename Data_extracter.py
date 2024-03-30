##Goal - extract as many stocks data as possible. 

#NEXT SESSION -1.Make sure I get stock data from ***all pages*** successfully 2.send stock data to DB, .



# Load the packages

import urllib.request
import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
import threading
# import Data_logger
# import subprocess
# import time

logging.basicConfig(filename='myapp.log', format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)

# Defining the url of the site
base_site = "https://finviz.com/screener.ashx"
# curUrl = "http://finviz.com/screener.ashx?v=151&f=idx_sp500&r=1"
base_len=len(base_site)


# Making a get request - WORKS
def get_response(url):
    response = requests.get(url, headers={
               'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
               })
    return response



# Extracting the HTML - WORKS
def from_response_to_soup(response):
    html = response.content
    soup = BeautifulSoup(html, "html.parser")
    with open('{}.html'.format(str(base_site)[8:1]), 'wb') as file:
        file.write(soup.prettify('utf-8'))
    return soup

def extract_num_of_pages(soup):
    pagination_Num = soup.find_all('a',{'class':'screener-pages'})  #Subjective part of code.
    num_Of_Pages = pagination_Num[len(pagination_Num)-2].text
    logging.info("Number of pages to scrape is {}".format(num_Of_Pages))
    return num_Of_Pages

# print (paginationNum[len(paginationNum)-1].text)


def get_stocks_in_page(soup):
    tickers = soup.find_all('a',{'class':'screener-link-primary'})  #Subjective part of code. WORKS, finds stock tickers
    print(tickers)
    companies_soup = soup.find_all('a',{'class':'screener-link'})  #gets all stock data !!!!
    print(companies_soup)
    companies_text = []
    for t in companies_soup:
        companies_text.append(t.text)
    print(companies_text)    
    companies = [companies_text[x:x+10] for x in range(0, len(companies_text), 10)] #10 is num of values each stock holds in array of entire stock data AKA companies_text
    for i in range(20):
        companies[i].append(tickers[i].text) 
    return companies    

# for t in tickers:
#     print(t.text)






# Companies records from home page are now complete
logging.info("Successfully scraped home page.")
# print(companies[19])


response = get_response(base_site)
home_soup = from_response_to_soup(response)
num_of_pages = int(extract_num_of_pages(home_soup))
stocks = get_stocks_in_page(home_soup)
print(stocks[19][3])


def get_and_send_stocks_from_page(i):    
    stock_index = 20*(i+1)+1
    url = 'http://finviz.com/screener.ashx?v=111&r={}'.format(stock_index)
    response = get_response(url)
    page_soup = from_response_to_soup(response)
    stocks = get_stocks_in_page(page_soup)
    for s in stocks:
        Data_logger.get_stock_and_log2DB(s)
    print(stocks[19])

def t1_stocks():
    for i in range(200):
        get_and_send_stocks_from_page(i)

def t2_stocks():
    for i in range(201, num_of_pages):
        get_and_send_stocks_from_page(i)

t1 = threading.Thread(target=t1_stocks, name='t1')
t2 = threading.Thread(target=t2_stocks, name='t2')

t1.start()
# t2.start()
