import json,re,requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from src import us_naver_links as nav
url=nav.resolve_us_url("GBTC")
code=urlsplit(url).path.split("/")[3]
base="https://api.stock.naver.com/chart/foreign/item/"+code
queries=[("day_3",base,{"periodType":"day","range":3}),
("day_1000",base,{"periodType":"day","range":1000}),
("month_100",base,{"periodType":"month","range":100}),
("month_1000",base,{"periodType":"month","range":1000}),
("dated_daily",base+"/day",{"startDateTime":"201301010000","endDateTime":"202611022359"}),
("dated_daily_compact",base+"/day",{"startDate":"20130101","endDate":"20261102"})]
def inspect(query):
    name,endpoint,params=query
    try:
        response=requests.get(endpoint,params=params,headers=nav.HEADERS,timeout=20)
        try:data=response.json()
        except Exception:data={}
        points=[]
        def walk(item):
            if isinstance(item,dict):
                if any("date" in key.lower() or "time" in key.lower() for key in item):
                    dates={key:value for key,value in item.items() if ("date" in key.lower() or "time" in key.lower()) and isinstance(value,(str,int))}
                    if dates:points.append({"dates":dates,"point":item if len(item)<15 else None})
                for value in item.values():walk(value)
            elif isinstance(item,list):
                for value in item:walk(value)
        if response.status_code==200:walk(data)
        return {"case":name,"url":endpoint,"params":params,"status":response.status_code,"keys":list(data)[:15] if isinstance(data,dict) else None,"count":len(points),"first":points[:2],"last":points[-2:],"error_prefix":response.text[:300] if response.status_code!=200 else None}
    except Exception as error:return {"case":name,"error":str(error)}
print("GBTC_NAVER_LINK:"+json.dumps({"url":url,"code":code}),flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:
    for row in pool.map(inspect,queries):print("GBTC_NAVER_RANGE_AUDIT:"+json.dumps(row,ensure_ascii=False),flush=True)
