"""Read-only source/pagination and price evidence for missing Korean ETFs."""
import json, logging
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import requests
from src import main as m
logging.basicConfig(level=logging.WARNING)
codes = ("225040", "418660", "409820")
url = "https://stock.naver.com/api/stockSecurity/etfs/v2/domestic"
def query(label, params):
    try:
        r=requests.get(url,headers=m.UA,params=params,timeout=20)
        data=r.json() if r.status_code==200 else {}
        rows=m._extract_rows(data)
        print("KR_PAGE_AUDIT:"+json.dumps({"label":label,"params":params,"status":r.status_code,"keys":list(data)[:20] if isinstance(data,dict) else None,"metadata":{k:v for k,v in data.items() if not isinstance(v,(list,dict))} if isinstance(data,dict) else None,"count":len(rows),"first":rows[0] if rows else None,"last":rows[-1] if rows else None,"codes":[str(row.get("itemcode") or row.get("itemCode") or row.get("code")) for row in rows],"target_rows":[row for row in rows if any(code in json.dumps(row) for code in codes)]},ensure_ascii=False),flush=True)
    except Exception as e:
        print("KR_PAGE_AUDIT:"+json.dumps({"label":label,"error":str(e)}),flush=True)
for index,size in ((0,300),(0,100),(1,100),(100,100),(2,100)):
    query(str(index)+"/"+str(size),{"listingType":"aumDesc","size":size,"index":index})
old=m.get_kr_etf_universe()
print("KR_OLD_UNIVERSE:"+json.dumps({"count":len(old),"target_membership":{code:code in old for code in codes},"nonbond":sum(not m.kr_is_bond_etf(row["name"]) for row in old.values())},ensure_ascii=False),flush=True)
anchor=m.get_trading_info()["kr_last"]
def prices(code):
    dates,closes=m._kr_price_history_dated(code,count=8000)
    pairs=[(d,p) for d,p in zip(dates,closes) if d<=anchor]
    if not pairs:
        return {"ticker":code,"no_history":True}
    dates,closes=map(list,zip(*pairs))
    row={"ticker":code,"market":"KOSPI","name":code}
    row.update(m._etf_price_performance(dates,closes,price_basis="네이버 차트 종가·배당조정 미확인",price_currency="KRW"))
    base=m.fetch_kr_etf_base(code)
    row.update(m.parse_kr_etf_base(base) if base else {})
    adjusted=m._kr_etf_adjusted_performance(code,"KOSPI",row)
    if adjusted:row.update(adjusted)
    row.update(m._validated_etf_metadata(row))
    row.update(m._etf_lifetime_metrics(row) or {})
    keys=("ticker","name","inception","inception_verified","price_start_date","price_end_date","initial_adjusted_price","latest_adjusted_price","cumulative_return","lifetime_cagr","lifetime_years","price_basis","return_ytd","return1y","return3y","return5y","return10y")
    return {k:row.get(k) for k in keys}|{"history_count":len(dates)}
with ThreadPoolExecutor(max_workers=3) as pool:
    for row in pool.map(prices,codes):print("KR_TARGET_AUDIT:"+json.dumps(row,ensure_ascii=False),flush=True)
try:
    r=requests.get("https://finance.naver.com/api/sise/etfItemList.nhn",headers=m.UA,timeout=20)
    data=r.json() if r.status_code==200 else {}
    rows=data.get("result",{}).get("etfItemList",[])
    print("KR_LEGACY_AUDIT:"+json.dumps({"status":r.status_code,"count":len(rows),"target_rows":[row for row in rows if row.get("itemcode") in codes]},ensure_ascii=False),flush=True)
except Exception as e: print("KR_LEGACY_AUDIT:"+json.dumps({"error":str(e)}),flush=True)
