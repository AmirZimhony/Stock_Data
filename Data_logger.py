#log data to DB

###NEXT SESSION  - 1. Define schema for stocks 2.add logic for checking if stock exists in DB. Make lists of new + deleted stocks. 


import pymongo
client = pymongo.MongoClient('mongodb://localhost:27017/stocky') #local host, need to change to production value. 

mydb = client['stock_data']

info = mydb.testTable

test_rec = [{
    "ticker":1,
    "company":'test'
}]

info.insert_many(test_rec)
# mongodb://localhost:27017/stocky

#added fields to each stock record - trending days, last_updated, trending percent (***look at stocky schema)



# //----------define our database structure----------

# StockSchema = {
#     'Ticker': {'type':String},
#     'Name': String,
#     'Price': String,
#     'MarketCap': Number,
#     'Country': String,
#     'Volume': Number,
#     'Sector': String,
#     'Industry': String,
#     'Change': Number,
#     'P/E': Number,    
#     'numOfRisingDays': Number,
#     'accumulatedChange': Number
# };

# def get_stock_and_log2DB(stock):
#     StockSchema[stock]
#     info.insert_one(StockSchema)

# StockSchema = {
#     Ticker: String,[10] constant
#     Name: String,[1] constant
#     Price: String,[7] changing
#     MarketCap: Number,[5] changing
#     Country: String,[4] constant
#     Volume: Number,[9] changing
#     Sector: String,[2] constant
#     Industry: String,[3], constant
#     Change: Number[8], constant
#     P/E: Number[6]     
#     numOfRisingDays: Number,
#     accumulatedChange: Number
# };
