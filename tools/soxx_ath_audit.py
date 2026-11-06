import json, requests
for day in ("20261104","20261105"):
    url=f"https://api.stock.naver.com/chart/foreign/item/SOXX.O/day?startDateTime={day}0000&endDateTime={day}2359"
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
    print("SOXX_NAVER_DAY:"+json.dumps({"url":url,"status":r.status_code,"data":r.json() if r.status_code==200 else r.text[:300]},ensure_ascii=False),flush=True)
