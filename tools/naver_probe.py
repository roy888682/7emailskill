import json
import requests
session=requests.Session()
session.headers["User-Agent"]="Mozilla/5.0"
for ticker in ("VZ","NVDA","TQQQ","SPY","BRK-B","SMH"):
    try:
        response=session.get("https://ac.stock.naver.com/ac",params={"q":ticker,"target":"stock,index,market"},timeout=20)
        print("AUTOCOMPLETE",ticker,response.status_code,response.url,response.text[:7000],flush=True)
    except Exception as error:
        print("PROBE_ERROR",ticker,str(error),flush=True)
for suffix in ("api/stock/VZ.N/basic","api/stock/TQQQ.O/basic","worldstock/stock/VZ.N/total","worldstock/etf/TQQQ.O/total"):
    try:
        response=session.get("https://m.stock.naver.com/"+suffix,timeout=20)
        print("DETAIL",suffix,response.status_code,response.url,response.text[:2500],flush=True)
    except Exception as error:
        print("PROBE_ERROR",suffix,str(error),flush=True)
