import json, math
from datetime import datetime, timedelta, timezone
import yfinance as yf
from src import main as m
info=m.get_trading_info()
anchor=info["us_last"]
report={"market_date":anchor.isoformat(),"funds":{}}
d1=m.dl(["TQQQ","UPRO","SPXL"],"1y",chunk=3,sleep=0)
cands=[tk for tk,s in d1.items() if len(s)>=2 and float(s.iloc[-1])>=float(s.max())*.90]
d2=m.dl(cands,"max",chunk=3,sleep=0)
for tk in ("TQQQ","UPRO","SPXL"):
    obj={"in_universe":tk in m.US_MAJOR_ETFS,"batch_1y_present":tk in d1,"passed_stage1":tk in cands,"batch_max_present":tk in d2}
    for key,batch in (("batch_1y",d1),("batch_max",d2)):
        if tk in batch:
            s=batch[tk]; obj[key]={"first":s.index[0].date().isoformat(),"last":s.index[-1].date().isoformat(),"last_close":float(s.iloc[-1]),"peak_close":float(s.max()),"gap_pct":(float(s.iloc[-1])/float(s.max())-1)*100}
    h=yf.Ticker(tk).history(period="max",end=(anchor+timedelta(days=1)).isoformat(),auto_adjust=True,actions=True,timeout=30)
    s=h["Close"].dropna(); s=s[[x.date()<=anchor for x in s.index]]
    d=[x.date() for x in s.index]; p=[float(x) for x in s.tolist()]
    perf=m._etf_price_performance(d,p,price_basis="Yahoo 제공 수정주가(auto_adjust)",price_currency="USD")
    vendor=yf.Ticker(tk).info or {}
    item={"ticker":tk,"market":"US","asset_type":"ETF","name":m.US_MAJOR_ETFS[tk],**perf,**m.enrich_us_etf(tk,m.US_MAJOR_ETFS[tk],1340)}
    meta=m._validated_etf_metadata(item); life=m._etf_lifetime_metrics(item)
    obj.update({"individual_rows":len(s),"first_date":d[0].isoformat(),"last_date":d[-1].isoformat(),"initial_adjusted_price":p[0],"latest_adjusted_price":p[-1],"peak_date":s.idxmax().date().isoformat(),"peak_adjusted_close":float(s.max()),"gap_pct":(p[-1]/float(s.max())-1)*100,"passes_alltime_10pct":p[-1]>=float(s.max())*.90,"perf":perf,"vendor_fundInceptionDate":vendor.get("fundInceptionDate"),"vendor_longBusinessSummary":vendor.get("longBusinessSummary"),"validated_inception":meta.get("inception"),"inception_mismatch":meta.get("price_history_inception_mismatch"),"lifetime_metrics":life,"raw_splits":{x.date().isoformat():float(v) for x,v in h["Stock Splits"].items() if v} if "Stock Splits" in h else {}})
    report["funds"][tk]=obj
m.get_us_tickers=lambda:(["TQQQ","UPRO","SPXL"],{x:"ETF" for x in ("TQQQ","UPRO","SPXL")},set(),dict(m.US_MAJOR_ETFS),{x:True for x in ("TQQQ","UPRO","SPXL")})
m.us_naver_links.resolve_us_links=lambda rows:None
rows=m.get_us_ath(1340)
report["production_three_ticker_result"]=[{"ticker":s["ticker"],"gap":s["gap"],"inception":s.get("inception"),"cumulative_return":s.get("cumulative_return"),"first_date":s.get("first_date")} for s in rows]
report["production_comparison"]=m.build_etf_info(rows,[])
print("TQQQ_PIPELINE_AUDIT:"+json.dumps(report,ensure_ascii=False,default=str),flush=True)
