import json, math
from datetime import date, timedelta
import requests
import yfinance as yf
from src import main as m

anchor = date(2026, 11, 5)
t = yf.Ticker("SOXX")
raw = t.history(period="max", end=(anchor+timedelta(days=1)).isoformat(), auto_adjust=False, actions=True, timeout=30)
adj = t.history(period="max", end=(anchor+timedelta(days=1)).isoformat(), auto_adjust=True, actions=True, timeout=30)
def summary(frame, case):
    result={"case":case,"rows":len(frame),"first":frame.index[0].date().isoformat(),"last":frame.index[-1].date().isoformat()}
    for col in ("Close","High","Adj Close"):
        if col in frame:
            series=frame[col].dropna()
            last=float(series.iloc[-1]);peak=float(series.max());peak_date=series.idxmax().date().isoformat()
            result[col]={"last":last,"peak":peak,"peak_date":peak_date,"gap":(last/peak-1)*100}
    result["recent"]=[{"date":idx.date().isoformat(),**{c:float(row[c]) for c in ("Close","High","Adj Close") if c in frame.columns}} for idx,row in frame.tail(15).iterrows()]
    print("SOXX_HISTORY:"+json.dumps(result),flush=True)
summary(raw,"unadjusted")
summary(adj,"adjusted")
print("SOXX_EVENTS:"+json.dumps([{"date":idx.date().isoformat(),"split":float(row["Stock Splits"]),"dividend":float(row["Dividends"])} for idx,row in raw.iterrows() if row.get("Stock Splits",0) or row.get("Dividends",0)]),flush=True)
for code in ("SOXX.O","SOXX.K","SOXX.P"):
    for url in (f"https://api.stock.naver.com/stock/{code}/basic",f"https://api.stock.naver.com/etf/{code}/basic"):
        try:
            r=requests.get(url,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                data=r.json()
                print("SOXX_NAVER_BASIC:"+json.dumps({"url":url,"data":data},ensure_ascii=False),flush=True)
                break
        except Exception as e:
            print("SOXX_NAVER_ERROR:"+json.dumps({"url":url,"type":type(e).__name__}),flush=True)
item={"ticker":"SOXX","market":"US","asset_type":"ETF","name":"SOXX","price_basis":"Yahoo 제공 수정주가(auto_adjust)"}
perf=m._refresh_etf_market_history(item,"US",anchor)
print("SOXX_CURRENT_REFETCH:"+json.dumps(perf,ensure_ascii=False),flush=True)

for end in ("2026-11-05","2026-11-06"):
    for adjusted in (False,True):
        history=yf.Ticker("SOXX").history(period="max",end=end,auto_adjust=adjusted,timeout=30)
        summary(history,"end="+end+" auto_adjust="+str(adjusted))
for adjusted in (False,True):
    history=yf.Ticker("SOXX").history(period="max",auto_adjust=adjusted,timeout=30)
    history=history[[stamp.date()<=date(2026,11,4) for stamp in history.index]]
    summary(history,"noend_trimNov4 auto_adjust="+str(adjusted))
