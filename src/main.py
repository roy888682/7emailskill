#!/usr/bin/env python3
import os, smtplib, logging, time, io, re, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz, yfinance as yf, requests
from bs4 import BeautifulSoup

# 구글 시트 패키지 로드
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_OK = True
except ImportError:
    GSPREAD_OK = False

def get_kr_industry(code: str):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        r = requests.get(url, headers=UA, timeout=5)
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
        m = re.search(r'sise_group_detail\.naver\?type=upjong[^"]*"[^>]*>\s*([^<]+?)\s*<', html)
        if m:
            val = m.group(1).strip()
            if val: return val
        return None
    except Exception:
        return None

INDUSTRY_KR = {
    "Technology":"기술","Healthcare":"헬스케어","Financial Services":"금융",
    "Consumer Cyclical":"경기소비재","Consumer Defensive":"필수소비재",
    "Industrials":"산업재","Energy":"에너지","Utilities":"유틸리티",
    "Real Estate":"부동산","Basic Materials":"소재","Communication Services":"커뮤니케이션서비스",
    "Semiconductors":"반도체","Semiconductor Equipment & Materials":"반도체 장비·소재",
    "Software—Infrastructure":"소프트웨어(인프라)","Software—Application":"소프트웨어(응용)",
    "Internet Content & Information":"인터넷 콘텐츠·정보","Internet Retail":"인터넷 소매",
    "Banks—Regional":"지역은행","Banks—Diversified":"종합은행",
    "Insurance—Diversified":"복합보험","Insurance—Property & Casualty":"손해보험",
    "Insurance—Life":"생명보험","Insurance—Specialty":"전문보험","Insurance Brokers":"보험중개",
    "Asset Management":"자산운용","Capital Markets":"자본시장",
    "Drug Manufacturers—General":"제약","Drug Manufacturers—Specialty & Generic":"특수·제네릭 제약",
    "Biotechnology":"바이오기술","Medical Devices":"의료기기","Medical Instruments & Supplies":"의료기기·용품",
    "Healthcare Plans":"건강보험","Diagnostics & Research":"진단·연구","Medical Care Facilities":"의료시설",
    "Specialty Retail":"전문소매","Discount Stores":"할인점","Restaurants":"외식업",
    "Auto Manufacturers":"자동차 제조","Auto Parts":"자동차 부품",
    "Aerospace & Defense":"항공우주·방위","Airlines":"항공",
    "Oil & Gas Integrated":"석유·가스(종합)","Oil & Gas E&P":"석유·가스 탐사생산",
    "Oil & Gas Midstream":"석유·가스 미드스트림","Oil & Gas Refining & Marketing":"정유·마케팅",
    "Oil & Gas Equipment & Services":"석유·가스 장비·서비스",
    "Utilities—Regulated Electric":"전력유틸리티","Utilities—Diversified":"종합유틸리티",
    "REIT—Diversified":"복합리츠","REIT—Retail":"리테일리츠","REIT—Residential":"주거리츠",
    "REIT—Office":"오피스리츠","REIT—Industrial":"산업용리츠","REIT—Healthcare Facilities":"헬스케어리츠",
    "Telecom Services":"통신서비스","Entertainment":"엔터테인먼트",
    "Electronic Gaming & Multimedia":"게임·멀티미디어","Consumer Electronics":"가전",
    "Specialty Chemicals":"특수화학","Chemicals":"화학","Building Materials":"건축자재",
    "Packaging & Containers":"포장재","Beverages—Non-Alcoholic":"음료(무알코올)",
    "Beverages—Wineries & Distilleries":"주류","Beverages—Brewers":"맥주",
    "Packaged Foods":"가공식품","Farm Products":"농산물",
    "Household & Personal Products":"생활용품","Apparel Manufacturing":"의류제조",
    "Apparel Retail":"의류소매","Footwear & Accessories":"신발·액세서리",
    "Credit Services":"신용서비스","Information Technology Services":"IT서비스",
    "Communication Equipment":"통신장비","Electronic Components":"전자부품",
    "Computer Hardware":"컴퓨터하드웨어","Scientific & Technical Instruments":"과학기술기기",
    "Industrial Distribution":"산업유통","Specialty Industrial Machinery":"특수산업기계",
    "Farm & Heavy Construction Machinery":"농기계·중장비","Metal Fabrication":"금속가공",
    "Railroads":"철도","Trucking":"화물운송","Integrated Freight & Logistics":"물류",
    "Marine Shipping":"해운","Waste Management":"폐기물관리",
    "Engineering & Construction":"엔지니어링·건설","Conglomerates":"복합기업",
    "Staffing & Employment Services":"인력파견","Security & Protection Services":"보안서비스",
    "Specialty Business Services":"전문비즈니스서비스","Consulting Services":"컨설팅서비스",
    "Gold":"금","Silver":"은","Copper":"구리","Steel":"철강","Aluminum":"알루미늄",
    "Lodging":"숙박","Resorts & Casinos":"리조트·카지노","Travel Services":"여행서비스",
    "Personal Services":"개인서비스","Education & Training Services":"교육·훈련서비스",
    "Tobacco":"담배","Confectioners":"제과","Grocery Stores":"식료품점",
    "Home Improvement Retail":"홈인테리어 소매","Department Stores":"백화점",
}

def get_us_industry(ticker: str):
    try:
        info = yf.Ticker(ticker).info
        ind = info.get("industry") or info.get("sector")
        if not ind: return None
        return INDUSTRY_KR.get(ind, ind)
    except Exception:
        return None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
UA  = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
       "Accept-Language":"ko-KR,ko;q=0.9"}

DOW30={"AAPL","MSFT","UNH","GS","HD","AMGN","CAT","CRM","CVX","BA",
       "MCD","HON","V","JPM","AXP","MRK","IBM","MMM","NKE","JNJ",
       "TRV","WMT","PG","VZ","DIS","KO","DOW","CSCO","WBA","NVDA"}

def get_usd_krw():
    try:
        h=yf.Ticker("USDKRW=X").history(period="5d",auto_adjust=True)
        r=float(h["Close"].iloc[-1]); log.info(f"USD/KRW:{r:,.1f}"); return r
    except: return 1380.0

def date_str(d):
    if d is None: return "확인불가"
    return d.strftime(f"%Y년 %m월 %d일({'월화수목금토일'[d.weekday()]})")

def prev_weekday(d):
    p=d-timedelta(days=1)
    while p.weekday()>=5: p-=timedelta(days=1)
    return p

def get_trading_info():
    today=datetime.now(KST).date(); expected=prev_weekday(today)
    def lt(sym):
        try:
            today_kst=datetime.now(KST).date()
            h=yf.Ticker(sym).history(period="10d",auto_adjust=True)
            if h.empty: return None
            dates=[d.date() if hasattr(d,"date") else d for d in h.index]
            past=[d for d in dates if d<today_kst]
            return max(past) if past else None
        except: return None
    us_last=lt("SPY"); kr_last=lt("005930.KS")
    us_hol=(us_last!=expected) if us_last else False
    kr_hol=(kr_last!=expected) if kr_last else False
    def hm(exp,act,mkt):
        if not act: return ""
        return f"직전 영업일({date_str(exp)})이 {mkt} 휴장이므로 직직전 영업일 기준: {date_str(act)}"
    log.info(f"오늘:{today} 직전평일:{expected} US:{us_last}(휴:{us_hol}) KR:{kr_last}(휴:{kr_hol})")
    return {"expected":expected,"us_last":us_last,"kr_last":kr_last,
            "us_last_str":date_str(us_last),"kr_last_str":date_str(kr_last),
            "us_holiday":us_hol,"kr_holiday":kr_hol,
            "us_holiday_msg":hm(expected,us_last,"미국") if us_hol else "",
            "kr_holiday_msg":hm(expected,kr_last,"한국") if kr_hol else ""}

def dl(tickers, period, chunk=80, sleep=1.2):
    out={}; n=len(tickers)
    if not n: return out
    for i in range(0,n,chunk):
        grp=tickers[i:i+chunk]; bn=i//chunk+1
        log.info(f"  US[{bn}/{(n+chunk-1)//chunk}] {i+1}~{min(i+chunk,n)}/{n} ({period})")
        try:
            raw=yf.download(grp,period=period,progress=False,auto_adjust=True,group_by="ticker")
            if raw.empty: time.sleep(sleep); continue
            for tk in grp:
                try:
                    s=(raw[tk]["Close"] if len(grp)>1 else raw["Close"]).dropna()
                    if len(s)>=10: out[tk]=s
                except: pass
        except Exception as e: log.error(f"  US[{bn}] {e}")
        time.sleep(sleep)
    log.info(f"  US완료:{len(out)}/{n}"); return out

def get_us_tickers():
    tickers=set(); exchange_map={}; sp500_set=set()
    for url,ec,tc,exch_name in [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",6,3,"NASDAQ"),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt",6,7,"NYSE"),
    ]:
        try:
            r=requests.get(url,headers=UA,timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                p=line.split("|")
                if len(p)<=max(ec,tc): continue
                sym=p[0].strip()
                if sym and not(len(p)>ec and p[ec].strip()=="Y") and not(len(p)>tc and p[tc].strip()=="Y") and sym.replace("-","").isalpha():
                    tickers.add(sym); exchange_map[sym]=exch_name
        except Exception as e: log.error(f"FTP:{e}")
    try:
        import pandas as pd
        r=requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",headers=UA,timeout=20)
        df=pd.read_html(io.StringIO(r.text))[0]
        for s in df["Symbol"].tolist():
            sym=str(s).replace(".","-"); tickers.add(sym); sp500_set.add(sym)
    except: pass
    result=sorted(tickers); log.info(f"미국 {len(result)}종목"); return result,exchange_map,sp500_set

def get_us_ath(usd_krw):
    tickers,exchange_map,sp500_set=get_us_tickers()
    if not tickers: return []
    d1=dl(tickers,"1y",chunk=100,sleep=1.0)
    cands=[tk for tk,s in d1.items() if len(s)>=2 and float(s.iloc[-1])>=float(s.max())*0.90]
    log.info(f"미국 1단계후보:{len(cands)}")
    if not cands: return []
    d2=dl(cands,"max",chunk=25,sleep=2.0)
    out=[]
    for tk,s in d2.items():
        try:
            last=float(s.iloc[-1]); prev=float(s.iloc[-2]); ath=float(s.max())
            if last>=ath*0.90:
                mcap=None
                try:
                    m=getattr(yf.Ticker(tk).fast_info,"market_cap",None) or 0
                    if m>0: mcap=round(m*usd_krw/1e12,1)
                except: pass
                idx=[]
                if tk in DOW30: idx.append("Dow")
                if tk in sp500_set: idx.append("S&P500")
                idx.append(exchange_map.get(tk,"NYSE"))
                url=f"https://m.stock.naver.com/worldstock/stock/{tk}/total"
                out.append({"ticker":tk,"name":tk,"price":round(last,2),
                            "change":round((last-prev)/prev*100,2),
                            "gap":round((last-ath)/ath*100,2),"mcap":mcap,
                            "index":idx,"industry":None,
                            "market":"US","url":url})
        except: pass
    if out:
        log.info(f"미국 업종 조회 중 ({len(out)}종목)...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs={ex.submit(get_us_industry,s["ticker"]):s for s in out}
            for fut in as_completed(futs):
                s=futs[fut]
                try: s["industry"]=fut.result()
                except: s["industry"]=None
    out.sort(key=lambda x:x["gap"])
    log.info(f"미국 최종:{len(out)}"); return out

def get_kr_ath(usd_krw, kr_last=None):
    try:
        import FinanceDataReader as fdr
    except Exception as e:
        log.error(f"fdr 로드실패:{e}"); return []

    start_date="2015-01-01"
    results=[]

    for market_name in ["KOSPI","KOSDAQ"]:
        try:
            df_list=fdr.StockListing(market_name)
            if df_list is None or df_list.empty: continue
        except: continue

        sym_col=next((c for c in ["Symbol","Code","종목코드"] if c in df_list.columns), None)
        nam_col=next((c for c in ["Name","종목명"] if c in df_list.columns), None)
        if not sym_col: continue

        codes=df_list[sym_col].astype(str).str.zfill(6).tolist()
        names={str(row[sym_col]).zfill(6): str(row[nam_col]) if nam_col else str(row[sym_col])
               for _,row in df_list.iterrows()}

        mcaps={}
        mc_col=next((c for c in ["Marcap","MarketCap","시가총액"] if c in df_list.columns),None)
        if mc_col:
            for _,row in df_list.iterrows():
                code=str(row[sym_col]).zfill(6)
                try:
                    v=float(row[mc_col])
                    if v>0: mcaps[code]=round(v/1e12,1)
                except: pass

        log.info(f"{market_name} {len(codes)}종목 ATH 분석 (
