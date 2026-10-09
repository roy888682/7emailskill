import requests,json
s=requests.Session()
s.headers["User-Agent"]="Mozilla/5.0"
for q in ("BRK.B","BRK B","BRK","BF-B","BF.B","BF B","JNJ","VZ"):
    try:
        r=s.get("https://ac.stock.naver.com/ac",params={"q":q,"target":"stock,index,market"},timeout=20)
        print("AUTOCOMPLETE",q,r.status_code,r.text[:9000],flush=True)
    except Exception as e:print("ERROR",q,str(e),flush=True)
for code in ("VZ","NVDA.O","TQQQ.O","SPY"):
    try:
        r=s.get("https://api.stock.naver.com/stock/"+code+"/basic",timeout=20)
        j=r.json()
        print("BASIC",code,r.status_code,json.dumps({k:j.get(k) for k in ("reutersCode","symbolCode","stockEndType","stockEndUrl","endUrl","stockExchangeType")},ensure_ascii=False),flush=True)
    except Exception as e:print("ERROR",code,str(e),flush=True)
