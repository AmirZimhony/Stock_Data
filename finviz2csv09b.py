import urllib.request
import pandas as pd
import threading
from datetime import datetime
import os
#from io import StringIO
from tabulate import tabulate 

mdfName = ['No.','Ticker', 'Company', 'Sector', 'Industry', 'Country', 'Market Cap', 'P/E', 'Fwd P/E', 'PEG', 'P/S',
           'P/B', 'P/C', 'P/FCF', 'Dividend', 'Payout Ratio', 'EPS', 'EPS this Y', 'EPS next Y', 'EPS past 5Y',
		   'EPS next 5Y', 'Sales past 5Y', 'EPS Q/Q', 'Sales Q/Q', 'Outstanding', 'Float', 'Insider Own', 'Insider Trans', 
		   'Inst Own', 'Inst Trans', 'Float Short', 'Short Ratio', 'ROA', 'ROE', 'ROI', 'Curr R', 'Quick R', 'LTDebt/Eq',
		   'Debt/Eq', 'Gross M', 'Oper M', 'Profit M', 'Perf Week', 'Perf Month', 'Perf Quart', 'Perf Half', 'Perf Year',
		   'Perf YTD', 'Beta', 'ATR', 'Volatility W', 'Volatility M', 'SMA20', 'SMA50', 'SMA200', '50D High', '50D Low',
		   '52W High', '52W Low', 'RSI', 'from Open', 'Gap', 'Recom', 'Avg Volume', 'Rel Volume', 'Price', 'Change',
		   'Volume', 'Earnings']
		   
fillds = '&c=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,' +\
         '24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,' +\
         '57,58,59,60,61,62,63,64,65,66,67,68'
mdf = pd.DataFrame(columns=mdfName)
ofile = 'spCsv/' + 'sp500_' + str(datetime.now().strftime('%Y-%m-%d')) + '.csv'
#lock = threading.Lock()


numOfPages = 26
finVizList = []
def urlList():
     tList = []
     for pageIndex in range(0, numOfPages + 1):
        curUrl = 'http://finviz.com/screener.ashx?v=151&f=idx_sp500&r=' + str(pageIndex*20 + 1) + fillds
        tList.append(curUrl)
     return(tList)
     
def readUrl(curUrl):
     print(curUrl)
     req = urllib.request.Request(
          curUrl,   
          data=None,
               headers={
               'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36'
               }
            )
     url = urllib.request.urlopen(req)
     t = pd.read_html(url, flavor='bs4')
     tn = t[11].drop([t[11].index[0]])
     #print(tn)
     tn.columns=mdfName
     return(pd.DataFrame(tn))
            
      
if __name__ == '__main__':
      finVizList = urlList()
      data = map(readUrl,  finVizList)
      #print(data)
      md = list(data)
      #md = pd.DataFrame(data, columns=mdfName)  
      mdf = pd.concat(md).drop(['No.'], axis=1)
      mdf.sort_values(by=['Ticker']).to_csv(ofile, index=False)
      dateTimeObj = datetime.now()
      dayStr = dateTimeObj.strftime("%Y-%m-%d")
      f = open('./spCsv/sp500_' + dayStr + '.txt',"w")
      secList = mdf['Sector'].drop_duplicates().to_list()
      mdf['bestInDay'] = mdf['Rel Volume'].apply(lambda x: float(x)) * mdf['Change'].apply(lambda x: float(x[:-1]))
      t = mdf[['Ticker' ,'Sector','Industry' , 'bestInDay', 'Recom','Inst Trans','Float Short','Short Ratio']]
      for sec in secList:
        #print(t[t['Sector'] == sec].sort_values('bestInDay', ascending=False))
        f.write(tabulate(t[t['Sector'] == sec].sort_values('bestInDay', ascending=False), headers='keys',  tablefmt='psql'))
      f.close()

