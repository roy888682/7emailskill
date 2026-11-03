import json,requests
from concurrent.futures import ThreadPoolExecutor
from src import us_naver_links as nav
url="https://api.stock.naver.com/chart/foreign/item/GBTC.K/day"
windows=[("ETF_first_days","202401090000","202401122359"),("spinoff_window","202407250000","202408022359"),("issuer_month_end","202609300000","202609302359")]
def inspect(window):
    name,start,end=window
    response=requests.get(url,params={"startDateTime":start,"endDateTime":end},headers=nav.HEADERS,timeout=20)
    data=response.json() if response.status_code==200 else {}
    rows=data if isinstance(data,list) else data.get("priceInfos",[])
    return {"case":name,"status":response.status_code,"points":[{key:row.get(key) for key in ("localDate","closePrice","openPrice")} for row in rows]}
with ThreadPoolExecutor(max_workers=3) as pool:
    for row in pool.map(inspect,windows):print("GBTC_NAVER_CORPORATE_ACTION_PRICES:"+json.dumps(row,ensure_ascii=False),flush=True)
