import json, math
import pandas as pd
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
import requests
from src import main as m
from src import us_naver_links as nav
anchor = m.get_trading_info()["us_last"]
ticker = m.yf.Ticker("GBTC")
raw = ticker.history(period="max", end=(anchor + timedelta(days=1)).isoformat(), auto_adjust=False, actions=True, timeout=30)
adjusted = ticker.history(period="max", end=(anchor + timedelta(days=1)).isoformat(), auto_adjust=True, actions=True, timeout=30)
closes = adjusted["Close"].dropna()
pairs = [(stamp.date(), float(value)) for stamp, value in closes.items() if stamp.date() <= anchor and math.isfinite(float(value)) and value > 0]
dates, prices = map(list, zip(*pairs))
def performance(label, cutoff=None, end_date=None):
    row = {"ticker":"GBTC", "market":"US", "asset_type":"ETF",
           "inception":cutoff or "2013-09-25", "inception_verified":True}
    scenario = [(day, price) for day, price in zip(dates, prices) if end_date is None or day <= date.fromisoformat(end_date)]
    scenario_dates, scenario_prices = map(list, zip(*scenario))
    row.update(m._etf_price_performance(scenario_dates, scenario_prices, not_before=cutoff, price_basis="Yahoo provided adjusted prices(auto_adjust)", price_currency="USD"))
    row.update(m._etf_lifetime_metrics(row) or {})
    keys = ("price_start_date","price_end_date","initial_adjusted_price","latest_adjusted_price","cumulative_return","lifetime_cagr","lifetime_years","return_ytd","return1y","return3y","return5y","return10y")
    print("GBTC_HISTORY_AUDIT:" + json.dumps({"case":label, "anchor":anchor.isoformat(), **{key:row.get(key) for key in keys}}, ensure_ascii=False), flush=True)
performance("old_full_OTC_plus_ETF_history")
performance("ETF_since_2024_01_11", "2024-01-11")
performance("ETF_monthend_issuer_comparison_2026_09_30", "2024-01-11", "2026-09-30")
samples = []
for stamp,row in raw.iterrows():
    day=stamp.date()
    if day<=anchor and (len(samples)<3 or day.isoformat() in ("2024-01-10","2024-01-11","2024-07-29","2024-07-30","2024-07-31","2024-08-01") or day==anchor):
        samples.append({"date":day.isoformat(), **{key:float(row[key]) for key in ("Close","Adj Close","Dividends","Stock Splits","Capital Gains") if key in raw.columns and pd.notna(row[key])}})
events=[]
for stamp,row in raw.iterrows():
    if any(key in raw.columns and pd.notna(row[key]) and float(row[key])!=0 for key in ("Dividends","Stock Splits","Capital Gains")):
        events.append({"date":stamp.date().isoformat(), **{key:float(row[key]) for key in ("Close","Adj Close","Dividends","Stock Splits","Capital Gains") if key in raw.columns and pd.notna(row[key])}})
print("GBTC_PRICE_AND_ACTION_AUDIT:"+json.dumps({"first_date":dates[0].isoformat(),"last_date":dates[-1].isoformat(),"observations":len(dates),"samples":samples,"events":events},ensure_ascii=False),flush=True)
try:
    link=nav.resolve_us_url("GBTC")
    code=urlsplit(link).path.split("/")[3]
    basic=nav._request_json("https://api.stock.naver.com/stock/"+code+"/basic")
    print("GBTC_NAVER_IDENTITY:"+json.dumps({"url":link,"code":code,"basic":basic},ensure_ascii=False),flush=True)
    queries=[
      ("stock_chart", "https://api.stock.naver.com/stock/"+code+"/chart", {"periodType":"month","range":"all"}),
      ("foreign_day_all", "https://api.stock.naver.com/chart/foreign/item/"+code, {"periodType":"day","range":"all"}),
      ("foreign_month_all", "https://api.stock.naver.com/chart/foreign/item/"+code, {"periodType":"month","range":"all"}),
      ("foreign_day_10y", "https://api.stock.naver.com/chart/foreign/item/"+code, {"periodType":"day","range":"10y"})]
    def chart(query):
        label,url,params=query
        try:
            response=requests.get(url,params=params,headers=m.UA,timeout=15)
            try:data=response.json()
            except Exception:data={}
            found=[]
            def walk(value):
                if isinstance(value,dict):
                    for key,item in value.items():
                        if isinstance(item,(str,int)) and any(part in key.lower() for part in ("date","time","traded")):
                            text=str(item)
                            if len(text)>=8 and text[:4].isdigit():found.append({"key":key,"value":text})
                        walk(item)
                elif isinstance(value,list):
                    for item in value:walk(item)
            walk(data)
            return {"case":label,"status":response.status_code,"keys":list(data)[:15] if isinstance(data,dict) else None,"date_count":len(found),"first_dates":found[:3],"last_dates":found[-3:],"body_prefix":response.text[:300] if not found else None}
        except Exception as error:return {"case":label,"error":str(error)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(chart,queries):print("GBTC_NAVER_CHART_AUDIT:"+json.dumps(result,ensure_ascii=False),flush=True)
except Exception as error:print("GBTC_NAVER_ERROR:"+json.dumps({"error":str(error)}),flush=True)
