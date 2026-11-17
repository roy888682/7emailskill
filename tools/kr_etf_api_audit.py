import json,re,urllib.request,concurrent.futures
from urllib.parse import urljoin
HEADERS={"User-Agent":"Mozilla/5.0","Accept-Language":"ko-KR,ko;q=0.9"}
URLS=[
"https://finance.naver.com/api/sise/etfItemList.nhn",
"https://stock.naver.com/api/stockSecurity/etfs/v2/domestic?listingType=aumDesc&size=100&index=0",
"https://stock.naver.com/domestic/etf",
"https://stock.naver.com/market/etf",
"https://m.stock.naver.com/domestic/etf/total",
]
def fetch(url):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=25) as r:
        raw=r.read()
        for codec in ("utf-8","cp949","euc-kr"):
            try:
                text=raw.decode(codec);break
            except UnicodeDecodeError:pass
        else:text=raw.decode("utf-8",errors="replace")
        data={"url":url,"status":r.status,"final_url":r.url,"bytes":len(raw),"codec":codec}
        try:
            parsed=json.loads(text)
            data["keys"]=list(parsed) if isinstance(parsed,dict) else None
            result=parsed.get("result",{}) if isinstance(parsed,dict) else {}
            rows=result.get("etfItemList") if isinstance(result,dict) else None
            if isinstance(rows,list):
                data["result_keys"]=list(result)
                data["row_count"]=len(rows)
                data["codes"]=[x.get("itemcode") for x in rows]
                data["samples"]=rows[:2]+rows[-2:]
            else:data["json_prefix"]=str(parsed)[:1000]
        except Exception:
            data["html_prefix"]=text[:300]
            scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',text)
            data["scripts"]=scripts
        return data,text
def run(url):
    try:return fetch(url)
    except Exception as e:return {"url":url,"error":str(e)},None
results=list(concurrent.futures.ThreadPoolExecutor(max_workers=5).map(run,URLS))
for data,text in results:
    print("KR_ETF_API_AUDIT:"+json.dumps(data,ensure_ascii=False),flush=True)
    if text and data.get("scripts"):
        scripts=[urljoin(data["url"],x) for x in data["scripts"] if ".js" in x]
        for jsurl in scripts[-6:]:
            try:
                jsdata,js=fetch(jsurl)
                snippets=[]
                for match in re.finditer(r'stockSecurity|etfs.{0,12}domestic|listingType|etfItemList|/api/[^" ]{0,120}',js):
                    snippets.append(js[max(0,match.start()-100):match.end()+180])
                    if len(snippets)>=50:break
                print("KR_ETF_BUNDLE_AUDIT:"+json.dumps({"url":jsurl,"bytes":len(js),"snippets":snippets},ensure_ascii=False),flush=True)
            except Exception as e:print("BUNDLE_ERROR:"+str(e),flush=True)
