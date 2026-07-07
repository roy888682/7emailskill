#!/usr/bin/env python3
import os, smtplib, logging, time, io, re, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_kr_industry(code: str):
    """finance.naver.com PC페이지 '동일업종비교' 링크에서 업종명 추출 (검증된 패턴)"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        r = requests.get(url, headers=UA, timeout=8)
        r.encoding = r.apparent_encoding or "utf-8"   # 자동 인코딩 감지 (깨짐 방지)
        html = r.text
        m = re.search(r'sise_group_detail\.naver\?type=upjong[^"]*"[^>]*>\s*([^<]+?)\s*<', html)
        if m:
            val = m.group(1).strip()
            if val: return val
        return None
    except Exception:
        return None

INDUSTRY_KR = {
    # GICS 11개 섹터
    "Technology":"기술","Healthcare":"헬스케어","Financial Services":"금융",
    "Consumer Cyclical":"경기소비재","Consumer Defensive":"필수소비재",
    "Industrials":"산업재","Energy":"에너지","Utilities":"유틸리티",
    "Real Estate":"부동산","Basic Materials":"소재","Communication Services":"커뮤니케이션서비스",
    # 세부 업종 (자주 등장하는 항목)
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
    """yfinance sector/industry 정보를 한글로 매핑해서 반환 (사전에 없으면 영문 그대로)"""
    try:
        info = yf.Ticker(ticker).info
        ind = info.get("industry") or info.get("sector")
        if not ind: return None
        return INDUSTRY_KR.get(ind, ind)
    except Exception:
        return None
import pytz, yfinance as yf, requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
UA  = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
       "Accept-Language":"ko-KR,ko;q=0.9"}

SNAPSHOT_FILE = "data/daily_snapshots.json"

def load_snapshots() -> dict:
    """거래일별 스냅샷 로드. 구조: {"US":{"2026-06-26":["AAPL",...]}, "KR":{...}}"""
    try:
        if os.path.exists(SNAPSHOT_FILE):
            with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"스냅샷 로드 실패: {e}")
    return {"US": {}, "KR": {}}

def save_snapshots(snapshots: dict) -> None:
    try:
        os.makedirs("data", exist_ok=True)
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)
        log.info("스냅샷 저장 완료")
    except Exception as e:
        log.error(f"스냅샷 저장 실패: {e}")

def compute_new_tickers(stocks: list, snapshots: dict, market_key: str, date_key: str):
    """
    같은 거래일(date_key)을 몇 번 재실행해도 항상 동일한 결과가 나오도록,
    '바로 직전 거래일' 스냅샷과만 비교한다 (누적 이력 전체와 비교하지 않음).
    """
    bucket = snapshots.setdefault(market_key, {})

    # date_key보다 엄격히 이전인 날짜들 중 최신 날짜 = 직전 거래일
    prior_dates = sorted(d for d in bucket if d < date_key)
    prev_set = set(bucket[prior_dates[-1]]) if prior_dates else None

    today_set = {s["ticker"] for s in stocks}

    if prev_set is None:
        # 최초 실행 → 오늘을 baseline으로만 저장, 신규 없음 (전부 신규 처리 안 함)
        new_set = set()
    else:
        new_set = today_set - prev_set

    # 오늘 거래일 스냅샷은 항상 "전체 후보 목록"으로 덮어쓴다 (재실행해도 동일 결과 보장)
    bucket[date_key] = sorted(today_set)

    new_stocks = [s for s in stocks if s["ticker"] in new_set]
    return new_stocks

def compute_streak_counts(snapshots: dict, market_key: str) -> dict:
    """
    별도 DB 없이 daily_snapshots.json만 재활용.
    각 티커가 저장된 거래일 스냅샷에 총 며칠 등장했는지 세기만 하면 됨 (오늘 포함).
    """
    counts = {}
    for date_key, tickers in snapshots.get(market_key, {}).items():
        for tk in tickers:
            counts[tk] = counts.get(tk, 0) + 1
    return counts

def new_tickers_html(new_us: list, new_kr: list) -> str:
    """신규 등장 종목 섹션 HTML — 0건이어도 국가별 카운트는 항상 크게 표시"""
    total = len(new_us) + len(new_kr)

    count_cards = f"""
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px">
      <div style="background:#fff3e0;border-radius:6px;padding:10px 20px">
        <div style="font-size:11px;color:#555">🇺🇸 미국 신규</div>
        <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(new_us)}종목</div>
      </div>
      <div style="background:#fce4ec;border-radius:6px;padding:10px 20px">
        <div style="font-size:11px;color:#555">🇰🇷 한국 신규</div>
        <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(new_kr)}종목</div>
      </div>
    </div>"""

    if total == 0:
        return f"""
        <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;
                    border-left:4px solid #bbb;box-shadow:0 1px 4px rgba(0,0,0,.08)">
          <h2 style="margin:0 0 12px;color:#1a1a2e;font-size:18px">🆕 신규 등장 종목</h2>
          {count_cards}
          <p style="margin:0;color:#888;font-size:12px">오늘 신규 종목 없음</p>
        </div>"""

    def row(s, flag, currency):
        lk  = s.get("url","#")
        gap = s.get("gap",0)
        gc  = "#e74c3c" if gap<=-5 else "#e67e22" if gap<=-1 else "#27ae60"
        pr  = f"{s['price']:,.2f}" if currency=="USD" else f"{s['price']:,}"
        ind = s.get("industry") or ""
        mc  = s.get("mcap")
        mcap_str = f"{mc:,.1f}조" if mc else "-"
        return (f"<tr style='border-bottom:1px solid #f0f0f0'>"
                f"<td style='padding:7px 10px'>{flag}</td>"
                f"<td style='padding:7px'><a href='{lk}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a></td>"
                f"<td style='padding:7px;color:#333'>{s['name']}</td>"
                f"<td style='padding:7px;text-align:right;color:#555;font-size:13px'>{mcap_str}</td>"
                f"<td style='padding:7px;font-size:12px;color:#888'>{ind}</td>"
                f"<td style='padding:7px;text-align:center;color:{gc};font-weight:bold'>{gap:+.1f}%</td>"
                f"<td style='padding:7px;text-align:right;color:#555'>{pr} {currency}</td>"
                f"</tr>")

    rows = ""
    for s in new_us: rows += row(s,"🇺🇸","USD")
    for s in new_kr: rows += row(s,"🇰🇷","KRW")

    return f"""
    <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;
                border-left:4px solid #f39c12;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <h2 style="margin:0 0 12px;color:#1a1a2e;font-size:18px">🆕 신규 등장 종목</h2>
      {count_cards}
      <p style="margin:0 0 10px;color:#888;font-size:12px">데이터베이스에 오늘 처음 등장한 종목</p>
      <table style="border-collapse:collapse;width:100%;font-size:14px">
        <thead>
          <tr style="background:#f39c12;color:#fff">
            <th style="padding:8px">국가</th>
            <th style="padding:8px;text-align:left">티커</th>
            <th style="padding:8px;text-align:left">종목명</th>
            <th style="padding:8px;text-align:right">시가총액</th>
            <th style="padding:8px;text-align:left">업종</th>
            <th style="padding:8px;text-align:center">ATH 괴리율</th>
            <th style="padding:8px;text-align:right">현재가</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

DOW30={"AAPL","MSFT","UNH","GS","HD","AMGN","CAT","CRM","CVX","BA",
       "MCD","HON","V","JPM","AXP","MRK","IBM","MMM","NKE","JNJ",
       "TRV","WMT","PG","VZ","DIS","KO","DOW","CSCO","WBA","NVDA"}

# ── 공통 ──────────────────────────────────────────────
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
            # 오늘 날짜 제외 — yfinance가 오늘 날짜를 포함해서 반환하는 경우 방지
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

# ── 미국: 2단계 yfinance ──────────────────────────────
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
                # 지수 레이블
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

# ── 한국: Naver Finance 전용 (yfinance .KS/.KQ, FDR, KRX API 전부 미사용) ──
# 근거: finance.naver.com은 이미 업종 조회로 접속 성공이 확인됐고,
#       yfinance .KS/.KQ 배치·FDR·data.krx.co.kr 은 GitHub Actions에서 반복적으로 0건 반환됨.
def _kr_market_sum_page(sosok: str, page: int) -> list:
    """네이버 시가총액 페이지 1장 파싱. 헤더 텍스트로 컬럼 위치를 찾아 구조 변경에 안전하게 대응."""
    url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
    r = requests.get(url, headers=UA, timeout=15)
    r.encoding = r.apparent_encoding or "euc-kr"
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="type_2")
    if not table:
        return []

    header_row = table.find("tr")
    header_texts = [h.get_text(strip=True) for h in header_row.find_all(["th","td"])] if header_row else []
    def col_idx(name):
        for i,h in enumerate(header_texts):
            if name in h: return i
        return None
    mcap_idx = col_idx("시가총액")

    out = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        a = None
        for td in tds:
            cand = td.find("a")
            if cand and "code=" in cand.get("href",""):
                a = cand
                break
        if not a:
            continue
        m = re.search(r"code=(\d+)", a.get("href",""))
        if not m:
            continue
        code = m.group(1)
        name = a.get_text(strip=True)

        mcap = None
        if mcap_idx is not None and mcap_idx < len(tds):
            try:
                v = tds[mcap_idx].get_text(strip=True).replace(",","")
                if v: mcap = round(float(v)/10000, 1)   # 억원 -> 조원
            except: pass

        out.append({"code":code, "name":name, "mcap":mcap})
    return out

def get_kr_universe() -> dict:
    """{code: {"name":..., "mcap":..., "market":"KOSPI"|"KOSDAQ"}} — 네이버 시가총액 페이지 전량 순회"""
    universe = {}
    for market_name, sosok in [("KOSPI","0"), ("KOSDAQ","1")]:
        empty_streak = 0
        for page in range(1, 60):
            try:
                rows = _kr_market_sum_page(sosok, page)
            except Exception as e:
                log.error(f"{market_name} p{page} 요청 실패: {e}")
                rows = []
            if not rows:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue
            empty_streak = 0
            for row in rows:
                universe[row["code"]] = {"name":row["name"], "mcap":row["mcap"], "market":market_name}
            time.sleep(0.25)
        log.info(f"{market_name}: {sum(1 for v in universe.values() if v['market']==market_name)}종목 (네이버 시가총액)")

    log.info(f"한국 전체 유니버스: {len(universe)}종목")
    return universe

def _kr_price_history(code: str, count: int = 3000) -> list:
    """네이버 fchart에서 일별 종가 리스트(오래된->최신 순) 반환"""
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
        r = requests.get(url, headers=UA, timeout=15)
        items = re.findall(r"""data=['"]([^'"]+)['"]""", r.text)
        closes = []
        for it in items:
            parts = it.split("|")
            if len(parts) >= 5:
                try:
                    c = float(parts[4])
                    if c > 0: closes.append(c)
                except: pass
        return closes
    except Exception:
        return []

def get_kr_ath(usd_krw, kr_last=None):
    universe = get_kr_universe()
    if not universe:
        log.error("한국 종목 유니버스 수집 완전 실패 — 0종목 반환")
        return []

    log.info(f"한국 {len(universe)}종목 fchart 가격이력 조회 시작 (15 workers)...")

    def fetch_one(code, meta):
        name = meta["name"]
        if "스팩" in name:
            return None
        closes = _kr_price_history(code, count=3000)
        if len(closes) < 30:
            return None
        last, prev, ath = closes[-1], closes[-2], max(closes)
        if last <= 0 or ath <= 0:
            return None
        if last >= ath * 0.90:
            return {"ticker":code, "name":name, "price":int(last),
                    "change":round((last-prev)/prev*100,2),
                    "gap":round((last-ath)/ath*100,2),
                    "mcap":meta.get("mcap"),
                    "index":[meta.get("market","KR")], "industry":None,
                    "market":meta.get("market","KR"),
                    "url":f"https://m.stock.naver.com/domestic/stock/{code}/total"}
        return None

    out = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(fetch_one, code, meta): code for code, meta in universe.items()}
        for fut in as_completed(futs):
            r = fut.result()
            if r: out.append(r)

    log.info(f"한국 ATH 후보: {len(out)}종목")

    if out:
        log.info(f"한국 업종 조회 중 ({len(out)}종목)...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs={ex.submit(get_kr_industry,s["ticker"]):s for s in out}
            for fut in as_completed(futs):
                s=futs[fut]
                try: s["industry"]=fut.result()
                except: s["industry"]=None

    before_etf_filter = len(out)
    out = [s for s in out if s.get("industry")]   # 업종 없음 = ETF로 간주하고 제외
    log.info(f"ETF 제외: {before_etf_filter}종목 → {len(out)}종목")

    out.sort(key=lambda x:x["gap"])
    log.info(f"한국 최종:{len(out)}")
    return out

# ── 이메일 ────────────────────────────────────────────
BADGE_COLOR={"Dow":"#e74c3c","S&P500":"#2980b9","NASDAQ":"#27ae60",
              "NYSE":"#7f8c8d","KOSPI":"#1a1a2e","KOSDAQ":"#8e44ad"}
def _badges(labels):
    if not labels: return ""
    return f"<div style='margin-top:2px;font-size:11px;color:#888'>{' · '.join(labels)}</div>"

def tbl_html(stocks,title,currency,holiday,date_s,hmsg=""):
    banner=f'<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 16px;margin-bottom:12px;font-size:13px;color:#856404">⚠️ {hmsg}</div>' if holiday and hmsg else ""
    if not stocks:
        return f"<h2 style='color:#333;margin-top:30px'>{title}</h2><p style='color:#666;font-size:13px'>기준일:{date_s}</p>{banner}<p style='color:#888'>해당 종목 없음</p>"
    fp=lambda p:f"{p:,.2f}" if currency=="USD" else f"{p:,}"
    fm=lambda m:f"{m:,.1f}조" if m else "-"
    rows=""
    for i,s in enumerate(stocks):
        bg="#f9f9f9" if i%2==0 else "#fff"
        cc="#c0392b" if s["change"]>0 else "#2980b9"; cs="+" if s["change"]>0 else ""
        gap=s.get("gap",0)
        gc="#e74c3c" if gap<=-5 else "#e67e22" if gap<=-1 else "#27ae60"
        lk=s.get("url","#")
        streak=s.get("streak",1)
        rows+=f"""<tr style='background:{bg}'>
          <td style='padding:8px 10px'><a href='{lk}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a></td>
          <td style='padding:8px;text-align:center;color:#888;font-size:12px'>{streak}일째</td>
          <td style='padding:8px;text-align:center;color:{gc};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right'>
            <span style='color:#555;font-size:13px'>{fm(s.get("mcap"))}</span>
            {_badges(s.get("index",[]))}
          </td>
          <td style='padding:8px;text-align:left;color:#666;font-size:12px'>{s.get("industry") or "-"}</td>
          <td style='padding:8px'><a href='{lk}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a></td>
          <td style='padding:8px;text-align:right'>{fp(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{cc};font-weight:bold'>{cs}{s['change']}%</td></tr>"""
    return f"""<h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#666;font-size:13px;margin:2px 0 8px'>기준일:{date_s} | ATH 괴리율 -10%에 가까운 순</p>{banner}
    <p style='color:#aaa;font-size:11px;margin:0 0 10px'>🔗 클릭→네이버 증권 | <span style='color:#e74c3c'>●</span>-5~-10% <span style='color:#e67e22'>●</span>-1~-5% <span style='color:#27ae60'>●</span>0~-1%</p>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead><tr style='background:#1a1a2e;color:#fff'>
        <th style='padding:10px;text-align:left'>티커</th><th style='padding:10px;text-align:center'>누적일수</th><th style='padding:10px;text-align:center'>ATH 괴리율</th>
        <th style='padding:10px;text-align:right'>시가총액</th><th style='padding:10px;text-align:left'>업종</th><th style='padding:10px;text-align:left'>종목명</th>
        <th style='padding:10px;text-align:right'>현재가</th><th style='padding:10px;text-align:right'>등락률</th>
      </tr></thead><tbody>{rows}</tbody></table>"""

def build_email(us,kr,info,usd_krw,new_us=None,new_kr=None):
    td=datetime.now(KST).strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:780px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 ATH 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:13px">발송일:{td} | ATH ~ -10% | USD/KRW {usd_krw:,.0f}원</p>
  </div>
  {new_tickers_html(new_us or [],new_kr or [])}
  <div style="background:#fff;padding:16px 20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08);display:flex;gap:16px;flex-wrap:wrap">
    <div style="background:#eaf4ff;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇺🇸 미국 ({info['us_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div></div>
    <div style="background:#eaffea;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇰🇷 한국 ({info['kr_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div></div>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)">
    {tbl_html(us,"🇺🇸 미국 전체 상장 보통주","USD",info["us_holiday"],info["us_last_str"],info.get("us_holiday_msg",""))}
    <div style="margin-top:36px"></div>
    {tbl_html(kr,"🇰🇷 한국 KOSPI/KOSDAQ 전체","KRW",info["kr_holiday"],info["kr_last_str"],info.get("kr_holiday_msg",""))}
  </div>
  <p style="font-size:11px;color:#bbb;margin-top:16px;text-align:center">자동 발송 | All Time High 기준 | 투자 권유 아님</p>
</body></html>"""

def build_subject(info):
    ut=" [휴장]" if info["us_holiday"] else ""; kt=" [휴장]" if info["kr_holiday"] else ""
    return f"📈 ATH | 🇺🇸{info['us_last_str']}{ut} / 🇰🇷{info['kr_last_str']}{kt}"

def send_email(html,subject):
    user=os.environ["GMAIL_USER"]; pwd=os.environ["GMAIL_APP_PASSWORD"]
    to=os.environ.get("RECIPIENT_EMAIL","ykhan@dacpole.com")
    msg=MIMEMultipart("alternative"); msg["Subject"]=subject; msg["From"]=user; msg["To"]=to
    msg.attach(MIMEText(html,"html"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(user,pwd); s.sendmail(user,to,msg.as_string())
    log.info(f"✅ 발송→{to}")

def main():
    log.info("=== ATH 리포트 시작 ===")
    info=get_trading_info(); usd_krw=get_usd_krw()
    us=get_us_ath(usd_krw)
    kr=get_kr_ath(usd_krw, info.get("kr_last"))

    # 거래일 기준 스냅샷 비교 (같은 거래일 재실행해도 항상 동일 결과)
    us_date_key = info["us_last"].isoformat() if info.get("us_last") else datetime.now(KST).strftime("%Y-%m-%d")
    kr_date_key = info["kr_last"].isoformat() if info.get("kr_last") else datetime.now(KST).strftime("%Y-%m-%d")

    snapshots = load_snapshots()
    log.info(f"불러온 스냅샷 누적 일수 — US: {len(snapshots.get('US',{}))}일치, KR: {len(snapshots.get('KR',{}))}일치 "
             f"(이 숫자가 매번 실행 후에도 늘지 않고 그대로면 git push가 저장에 실패하고 있다는 뜻)")
    new_us = compute_new_tickers(us, snapshots, "US", us_date_key)
    new_kr = compute_new_tickers(kr, snapshots, "KR", kr_date_key)
    log.info(f"신규 티커: US {len(new_us)}개, KR {len(new_kr)}개 (US기준일:{us_date_key} KR기준일:{kr_date_key})")

    # 누적 등장 횟수 (오늘 스냅샷이 이미 반영된 상태이므로 오늘 포함해서 카운트됨)
    us_streak = compute_streak_counts(snapshots, "US")
    kr_streak = compute_streak_counts(snapshots, "KR")
    for s in us: s["streak"] = us_streak.get(s["ticker"], 1)
    for s in kr: s["streak"] = kr_streak.get(s["ticker"], 1)

    send_email(build_email(us,kr,info,usd_krw,new_us,new_kr), build_subject(info))

    # 스냅샷 저장 (Actions에서 push됨)
    save_snapshots(snapshots)
    log.info(f"=== 완료: US{len(us)} KR{len(kr)} / 신규 US{len(new_us)} KR{len(new_kr)} ===")

if __name__=="__main__": main()
