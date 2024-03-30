##Goal - extract as many stocks data as possible.
#Todo: Imitate Israel's method of scanning all pagination indexes of a page. 

#NEXT SESSION -1.Make sure I get stock data from ***all pages*** successfully 2.send stock data to DB, .



# Load the packages

import urllib.request
import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
# import subprocess
# import time

logging.basicConfig(filename='myapp.log', format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)

# Defining the url of the site
base_site = "https://finviz.com/screener.ashx"
curUrl = "http://finviz.com/screener.ashx?v=151&f=idx_sp500&r=1"
base_len=len(base_site)


# Making a get request - WORKS
response = requests.get(base_site, headers={
               'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
               })



# Extracting the HTML - WORKS
html = response.content


soup = BeautifulSoup(html, "html.parser")
with open('{}.html'.format(str(base_site)[8:1]), 'wb') as file:
    file.write(soup.prettify('utf-8'))
paginationNum = soup.find_all('a',{'class':'screener-pages'})  #Subjective part of code. 
# print (paginationNum[len(paginationNum)-1].text)
numOfPages = paginationNum[len(paginationNum)-2].text
print(numOfPages)
logging.info("Number of pages to scrape is {}".format(numOfPages))
print(len(paginationNum))



def get_stocks_for_single_page(self,i):
    return


tickers = soup.find_all('a',{'class':'screener-link-primary'})  #Subjective part of code. WORKS, finds stock tickers

# for t in tickers:
#     print(t.text)

companies_soup = soup.find_all('a',{'class':'screener-link'})  #gets all stock data !!!!



companies_text = []
for i in range(20):
# for t in companies_soup:
    companies_text.append(tickers[i].text)
    companies_text.append(companies_soup[i].text)
    # companies_text.append(t.text)
companies = [companies_text[x:x+10] for x in range(0, len(companies_text), 10)]

print(companies[1])
# print(len(companies))
# for t in companies:
#     print(t.text)


# def parse_stock_data(self, stocks):
#         for s in stocks:
#         print(t.text)