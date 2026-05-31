#!/usr/bin/env python3
"""
Daily ATH Stock Email — 2단계 방식
1단계: 전체 종목 1년 데이터로 빠른 스크리닝
2단계: 후보 종목만 max 데이터로 진짜 ATH 검증
"""
import os, smtplib, logging, time, io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
import pytz, yfinance as yf, requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
UA  = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
       "Accept-Language":"ko-KR,ko;q=0.9,en-US;q=0.8"}

# ── 환율 ──────────────────────────────────────────
def get_usd_krw():
    try:
        h = yf.Ticker("USDKRW=X").history(period="5d", auto_adjust=True)
        r = float(h["Close"].iloc[-1]); log.info(f"USD/KRW: {r:,.1f}"); return r
    except: return 1380.0

# ── 직전 거래일 ────────────────────────────────────
def date_str(d):
    if d is None: return "확인불가"
    return d.strftime(f"%Y년 %m월 %d일({'월화수목금토일'[d.weekday()]})")

def prev_weekday(d):
    p = d - timedelta(days=1)
    while p.weekday() >= 5: p -= timedelta(days=1)
    return p

def get_trading_info():
    today    = datetime.now(KST).date()
    expected = prev_weekday(today)
    def last_trade(sym):
        try:
            h = yf.Ticker(sym).history(period="10d", auto_adjust=True)
            if h.empty: return None
            last = h.index[-1]; return last.date() if hasattr(last,"date") else last
        except: return None
    us_last = last_trade("SPY"); kr_last = last_trade("005930.KS")
    us_hol  = (us_last != expected) if us_last else False
    kr_hol  = (kr_last != expected) if kr_last else False
    def hmsg(exp, act, mkt):
        if not act: return ""
        return f"직전 영업일({date_str(exp)})이 {mkt} 휴장이므로 직직전 영업일 기준: {date_str(act)}"
    log.info(f"오늘:{today} 직전평일:{expected} US:{us_last}(휴:{us_hol}) KR:{kr_last}(휴:{kr_hol})")
    return {"expected":expected, "us_last":us_last, "kr_last":kr_last,
            "us_last_str":date_str(us_last), "kr_last_str":date_str(kr_last),
            "us_holiday":us_hol, "kr_holiday":kr_hol,
            "us_holiday_msg":hmsg(expected,us_last,"미국") if us_hol else "",
            "kr_holiday_msg":hmsg(expected,kr_last,"한국") if kr_hol else ""}

# ── 시가총액 ───────────────────────────────────────
def get_mcap(yfc, usd_krw, is_kr=False):
    try:
        info = yf.Ticker(yfc).fast_info
        m = getattr(info,"market_cap",None) or 0
        if m<=0: return None
        return round((m/1e12) if is_kr else (m*usd_krw/1e12), 1)
    except: return None

# ── 배치 다운로드 핵심 함수 ────────────────────────
def dl(tickers, period, chunk=80, sleep=1.2):
    """검증된 group_by=ticker 방식 배치 다운로드"""
    out = {}; n = len(tickers)
    if n == 0: return out
    for i in range(0, n, chunk):
        grp = tickers[i:i+chunk]; bn = i//chunk+1
        log.info(f"  [{bn}/{(n+chunk-1)//chunk}] {i+1}~{min(i+chunk,n)}/{n} ({period})")
        try:
            raw = yf.download(grp, period=period, progress=False, auto_adjust=True, group_by="ticker")
            if raw.empty: log.warning(f"  [{bn}] 빈결과"); time.sleep(sleep); continue
            for tk in grp:
                try:
                    s = (raw[tk]["Close"] if len(grp)>1 else raw["Close"]).dropna()
                    if len(s)>=10: out[tk]=s
                except: pass
            log.info(f"  [{bn}] {sum(1 for tk in grp if tk in out)}개 수집")
        except Exception as e: log.error(f"  [{bn}] 오류: {e}")
        time.sleep(sleep)
    log.info(f"  배치완료: {len(out)}/{n}"); return out

def screen_candidates(data_1y, threshold=0.90):
    """1년 데이터에서 1년 고가 -10% 이내 후보 추출"""
    return [tk for tk,s in data_1y.items()
            if len(s)>=2 and float(s.iloc[-1]) >= float(s.max())*threshold]

def find_ath(data_max, threshold=0.90):
    """max 데이터에서 진짜 ATH -10% 이내 종목 추출"""
    out = []
    for tk,s in data_max.items():
        try:
            last=float(s.iloc[-1]); prev=float(s.iloc[-2]); ath=float(s.max())
            if last >= ath*threshold:
                out.append({"ticker":tk,"price":last,"change":round((last-prev)/prev*100,2),
                            "ath":ath,"gap":round((last-ath)/ath*100,2)})
        except: continue
    return out

# ── 미국 전체 종목 ────────────────────────────────
def get_us_tickers():
    tickers = set()
    for url,ecol,tcol in [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",6,3),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt", 6,7),
    ]:
        try:
            r=requests.get(url,headers=UA,timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                p=line.split("|")
                if len(p)<=max(ecol,tcol): continue
                sym=p[0].strip()
                etf  = len(p)>ecol and p[ecol].strip()=="Y"
                test = len(p)>tcol and p[tcol].strip()=="Y"
                if sym and not etf and not test and sym.replace("-","").isalpha():
                    tickers.add(sym)
            log.info(f"  FTP {url.split('/')[-1]}: 누적{len(tickers)}")
        except Exception as e: log.error(f"  FTP실패: {e}")

    # fallback: Wikipedia S&P500
    if len(tickers) < 100:
        log.info("  S&P500 Wikipedia fallback...")
        try:
            import pandas as pd
            r=requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",headers=UA,timeout=20)
            df=pd.read_html(io.StringIO(r.text))[0]
            for sym in df["Symbol"].str.replace(".","−",regex=False).tolist():
                tickers.add(sym.replace("−","-"))
            log.info(f"  Wikipedia S&P500 추가: {len(tickers)}")
        except Exception as e: log.error(f"  Wikipedia실패: {e}")

    result=sorted(tickers); log.info(f"미국 전체 {len(result)}종목"); return result

def get_us_ath(usd_krw):
    tickers = get_us_tickers()
    if not tickers: log.error("미국 티커 없음"); return []

    # 1단계: 1년 데이터로 빠른 스크리닝
    log.info(f"미국 1단계: {len(tickers)}종목 1년 데이터")
    data_1y = dl(tickers, "1y", chunk=100, sleep=1.0)
    cands   = screen_candidates(data_1y, threshold=0.90)
    log.info(f"미국 1단계 후보: {len(cands)}종목")

    if not cands: return []

    # 2단계: 후보만 max 데이터로 ATH 검증
    log.info(f"미국 2단계: {len(cands)}종목 max 데이터 ATH 검증")
    data_max = dl(cands, "max", chunk=25, sleep=2.0)
    ath_list = find_ath(data_max, threshold=0.90)
    log.info(f"미국 ATH 확정: {len(ath_list)}종목 → 시가총액")

    out = []
    for c in ath_list:
        tk=c["ticker"]
        out.append({**c,"name":tk,"price":round(c["price"],2),
                    "mcap":get_mcap(tk,usd_krw,is_kr=False),"market":"US",
                    "url":f"https://m.stock.naver.com/worldstock/stock/{tk}/total"})
    out.sort(key=lambda x:x["gap"],reverse=True)
    log.info(f"미국 최종 {len(out)}종목"); return out

# ── 한국 전체 종목 ────────────────────────────────
def get_kr_tickers():
    tickers = []
    # 1순위: pykrx
    try:
        from pykrx import stock as pk
        today=datetime.now(KST).strftime("%Y%m%d")
        for market,suffix in [("KOSPI",".KS"),("KOSDAQ",".KQ")]:
            try:
                codes=pk.get_market_ticker_list(today,market=market)
                for code in codes:
                    try: name=pk.get_market_ticker_name(code)
                    except: name=code
                    tickers.append({"code":code,"name":name,"market":market,
                                    "yf":f"{code}{suffix}",
                                    "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                log.info(f"pykrx {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e: log.error(f"pykrx {market}: {e}")
    except Exception as e: log.error(f"pykrx로드: {e}")
    # 2순위: KRX API
    if not tickers:
        for market,mid,suf in [("KOSPI","STK",".KS"),("KOSDAQ","KSQ",".KQ")]:
            try:
                r=requests.post("http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    data={"bld":"dbms/MDC/STAT/standard/MDCSTAT01901","mktId":mid,"share":"1","csvxls_isNo":"false"},
                    headers={**UA,"Referer":"http://data.krx.co.kr/"},timeout=30)
                for item in r.json().get("OutBlock_1",[]):
                    code=item.get("ISU_SRT_CD","").strip(); name=item.get("ISU_ABBRV","").strip()
                    if code and name:
                        tickers.append({"code":code,"name":name,"market":market,"yf":f"{code}{suf}",
                                        "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                log.info(f"KRX {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e: log.error(f"KRX {market}: {e}")
    # 3순위: 네이버 신고가 (최소 보장)
    if not tickers:
        log.info("네이버 신고가 fallback...")
        nh={**UA,"Referer":"https://finance.naver.com/sise/"}
        for sosok,market,suf in [("0","KOSPI",".KS"),("1","KOSDAQ",".KQ")]:
            for page in range(1,30):
                try:
                    r=requests.get(f"https://finance.naver.com/sise/sise_high.nhn?sosok={sosok}&page={page}",headers=nh,timeout=15)
                    r.encoding="euc-kr"
                    soup=BeautifulSoup(r.text,"html.parser")
                    tbl=soup.find("table",class_="type_2")
                    if not tbl: break
                    found=False
                    for row in tbl.find_all("tr"):
                        cols=row.find_all("td")
                        if len(cols)<4: continue
                        a=cols[0].find("a")
                        if not a: continue
                        href=a.get("href",""); code=href.split("code=")[-1].strip() if "code=" in href else ""
                        name=a.text.strip()
                        if code and name:
                            tickers.append({"code":code,"name":name,"market":market,"yf":f"{code}{suf}",
                                            "url":f"https://finance.naver.com/item/main.naver?code={code}"}); found=True
                    if not found: break
                except: break
    log.info(f"한국 전체 {len(tickers)}종목"); return tickers

def get_kr_ath(usd_krw):
    all_tk=get_kr_tickers()
    if not all_tk: log.error("한국 티커 없음"); return []
    yfc=[t["yf"] for t in all_tk]; meta={t["yf"]:t for t in all_tk}

    # 1단계: 1년 스크리닝
    log.info(f"한국 1단계: {len(yfc)}종목 1년 데이터")
    data_1y=dl(yfc,"1y",chunk=60,sleep=1.0)
    cands=screen_candidates(data_1y,threshold=0.90)
    log.info(f"한국 1단계 후보: {len(cands)}종목")
    if not cands: return []

    # 2단계: max 데이터 ATH 검증
    log.info(f"한국 2단계: {len(cands)}종목 max ATH 검증")
    data_max=dl(cands,"max",chunk=20,sleep=2.0)
    ath_list=find_ath(data_max,threshold=0.90)
    log.info(f"한국 ATH 확정: {len(ath_list)}종목 → 시가총액")

    out=[]
    for c in ath_list:
        yf_code=c["ticker"]; m=meta.get(yf_code,{})
        out.append({**c,"ticker":m.get("code",yf_code),"name":m.get("name",yf_code),
                    "price":int(c["price"]),"mcap":get_mcap(yf_code,usd_krw,is_kr=True),
                    "market":m.get("market","KR"),"url":m.get("url","#")})
    out.sort(key=lambda x:x["gap"],reverse=True)
    log.info(f"한국 최종 {len(out)}종목"); return out

# ── 이메일 HTML ───────────────────────────────────
def tbl_html(stocks, title, currency, holiday, date_s, hmsg=""):
    banner = f'<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 16px;margin-bottom:12px;font-size:13px;color:#856404">⚠️ {hmsg}</div>' if holiday and hmsg else ""
    if not stocks:
        return f"<h2 style='color:#333;margin-top:30px'>{title}</h2><p style='color:#666;font-size:13px'>기준일: {date_s}</p>{banner}<p style='color:#888'>해당 종목 없음</p>"
    fp=lambda p:f"{p:,.2f}" if currency=="USD" else f"{p:,}"
    fm=lambda m:f"{m:,.1f}조" if m else "-"
    rows=""
    for i,s in enumerate(stocks):
        bg="#f9f9f9" if i%2==0 else "#fff"
        cc="#c0392b" if s["change"]>0 else "#2980b9"; cs="+" if s["change"]>0 else ""
        gap=s.get("gap",0); gc="#27ae60" if gap>=-1 else "#e67e22" if gap>=-5 else "#e74c3c"
        lk=s.get("url","#")
        rows+=f"""<tr style='background:{bg}'>
          <td style='padding:8px 10px'><a href='{lk}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a></td>
          <td style='padding:8px;text-align:center;color:{gc};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right;color:#555;font-size:13px'>{fm(s.get("mcap"))}</td>
          <td style='padding:8px'><a href='{lk}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a></td>
          <td style='padding:8px;text-align:right'>{fp(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{cc};font-weight:bold'>{cs}{s['change']}%</td></tr>"""
    return f"""<h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#666;font-size:13px;margin:2px 0 8px'>기준일: {date_s}</p>{banner}
    <p style='color:#aaa;font-size:11px;margin:0 0 10px'>🔗 티커 클릭 → 네이버 증권 | <span style='color:#27ae60'>●</span>0~-1% <span style='color:#e67e22'>●</span>-1~-5% <span style='color:#e74c3c'>●</span>-5~-10%</p>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead><tr style='background:#1a1a2e;color:#fff'>
        <th style='padding:10px;text-align:left'>티커</th><th style='padding:10px;text-align:center'>ATH 괴리율</th>
        <th style='padding:10px;text-align:right'>시가총액</th><th style='padding:10px;text-align:left'>종목명</th>
        <th style='padding:10px;text-align:right'>현재가</th><th style='padding:10px;text-align:right'>등락률</th>
      </tr></thead><tbody>{rows}</tbody></table>"""

def build_email(us,kr,info,usd_krw):
    td=datetime.now(KST).strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:780px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 ATH 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:13px">발송일: {td} | ATH 종가 ~ -10% 이내 | USD/KRW {usd_krw:,.0f}원</p>
  </div>
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
    {tbl_html(kr,"🇰🇷 한국 KOSPI / KOSDAQ 전체","KRW",info["kr_holiday"],info["kr_last_str"],info.get("kr_holiday_msg",""))}
  </div>
  <p style="font-size:11px;color:#bbb;margin-top:16px;text-align:center">자동 발송 | All Time High 기준 | 투자 권유 아님</p>
</body></html>"""

def build_subject(info):
    ut=" [휴장]" if info["us_holiday"] else ""; kt=" [휴장]" if info["kr_holiday"] else ""
    return f"📈 ATH 리포트 | 🇺🇸 {info['us_last_str']}{ut} / 🇰🇷 {info['kr_last_str']}{kt}"

def send_email(html,subject):
    user=os.environ["GMAIL_USER"]; pwd=os.environ["GMAIL_APP_PASSWORD"]
    to=os.environ.get("RECIPIENT_EMAIL","ykhan@dacpole.com")
    msg=MIMEMultipart("alternative"); msg["Subject"]=subject; msg["From"]=user; msg["To"]=to
    msg.attach(MIMEText(html,"html"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(user,pwd); s.sendmail(user,to,msg.as_string())
    log.info(f"✅ 발송완료 → {to}")

def main():
    log.info("=== ATH 리포트 시작 ===")
    info=get_trading_info(); usd_krw=get_usd_krw()
    us=get_us_ath(usd_krw); kr=get_kr_ath(usd_krw)
    send_email(build_email(us,kr,info,usd_krw), build_subject(info))
    log.info(f"=== 완료: 미국{len(us)} / 한국{len(kr)} ===")

if __name__=="__main__": main()
