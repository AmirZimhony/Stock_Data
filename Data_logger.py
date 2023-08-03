#log data to DB


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

# const StockSchema = new mongoose.Schema({
#     Symbol: String,
#     Name: String,
#     prevPrice: String,
#     MarketCap: Number,
#     Country: String,
#     IPOYear: Number,
#     Volume: Number,
#     Sector: String,
#     Industry: String,
#     numOfRisingDays: Number,
#     accumulatedChange: Number
# });
