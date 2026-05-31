#!/usr/bin/env python3
"""
Daily ATH Stock Email — 완전판
전체 미국 + 전체 한국 | ATH ~ -10% | 괴리율 + 시가총액 + 휴장 감지
"""
import os, smtplib, logging, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date

import pytz
import yfinance as yf
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}

# ── 환율 ──────────────────────────────────────────────
def get_usd_krw() -> float:
    try:
        h = yf.Ticker("USDKRW=X").history(period="5d", auto_adjust=True)
        rate = float(h["Close"].iloc[-1])
        log.info(f"USD/KRW: {rate:,.1f}")
        return rate
    except: return 1380.0

# ── 직전 거래일 감지 ──────────────────────────────────
def date_str(d) -> str:
    if d is None: return "확인불가"
    w = ["월","화","수","목","금","토","일"][d.weekday()]
    return d.strftime(f"%Y년 %m월 %d일({w})")

def prev_weekday(d: date) -> date:
    p = d - timedelta(days=1)
    while p.weekday() >= 5: p -= timedelta(days=1)
    return p

def last_trade(ticker_str: str):
    try:
        h = yf.Ticker(ticker_str).history(period="10d", auto_adjust=True)
        if h.empty: return None
        last = h.index[-1]
        return last.date() if hasattr(last,"date") else last
    except: return None

def get_trading_info() -> dict:
    today    = datetime.now(KST).date()
    expected = prev_weekday(today)
    us_last  = last_trade("SPY")
    kr_last  = last_trade("005930.KS")
    us_hol   = (us_last != expected) if us_last else False
    kr_hol   = (kr_last != expected) if kr_last else False
    def hmsg(exp, act, mkt):
        if not act: return ""
        return f"직전 영업일({date_str(exp)})이 {mkt} 휴장이므로 직직전 영업일 기준: {date_str(act)}"
    log.info(f"오늘KST:{today} 직전평일:{expected} US:{us_last}(휴장:{us_hol}) KR:{kr_last}(휴장:{kr_hol})")
    return {
        "expected":expected, "us_last":us_last, "kr_last":kr_last,
        "us_last_str":date_str(us_last), "kr_last_str":date_str(kr_last),
        "us_holiday":us_hol, "kr_holiday":kr_hol,
        "us_holiday_msg":hmsg(expected,us_last,"미국") if us_hol else "",
        "kr_holiday_msg":hmsg(expected,kr_last,"한국") if kr_hol else "",
    }

# ── 시가총액 ──────────────────────────────────────────
def get_mcap(yf_code: str, usd_krw: float, is_kr=False):
    try:
        info = yf.Ticker(yf_code).fast_info
        mcap = getattr(info,"market_cap",None) or 0
        if mcap <= 0: return None
        return round((mcap/1e12) if is_kr else (mcap*usd_krw/1e12), 1)
    except: return None

# ── 배치 다운로드 (버전 #9 검증 방식) ─────────────────
def batch_download(tickers: list, period="max", chunk=50) -> dict:
    result = {}
    n = len(tickers)
    log.info(f"  {n}종목 / 청크{chunk} / {(n+chunk-1)//chunk}배치")
    for i in range(0, n, chunk):
        grp = tickers[i:i+chunk]
        bn  = i//chunk+1
        log.info(f"  배치[{bn}] {i+1}~{min(i+chunk,n)}/{n}")
        try:
            raw = yf.download(grp, period=period, progress=False, auto_adjust=True, group_by="ticker")
            if raw.empty:
                log.warning(f"  배치[{bn}] 빈 결과")
                continue
            for tk in grp:
                try:
                    s = (raw[tk]["Close"] if len(grp)>1 else raw["Close"]).dropna()
                    if len(s) >= 30:
                        result[tk] = s
                except: pass
        except Exception as e:
            log.error(f"  배치[{bn}] 오류: {e}")
        time.sleep(1.5)
    log.info(f"  완료: {len(result)}/{n}종목")
    return result

def find_ath(data: dict, threshold=0.90) -> list:
    out = []
    for tk, s in data.items():
        try:
            last = float(s.iloc[-1]); prev = float(s.iloc[-2]); ath = float(s.max())
            if last >= ath * threshold:
                out.append({"ticker":tk,"price":last,"change":round((last-prev)/prev*100,2),
                            "ath":ath,"gap":round((last-ath)/ath*100,2)})
        except: continue
    return out

# ── 미국 전체 종목 ─────────────────────────────────────
def get_us_tickers() -> list:
    tickers = set()
    for url,ecol,tcol in [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",6,3),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt", 6,7),
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                p = line.split("|")
                if len(p) <= max(ecol,tcol): continue
                sym=p[0].strip()
                if (sym and not (len(p)>ecol and p[ecol].strip()=="Y")
                       and not (len(p)>tcol and p[tcol].strip()=="Y")
                       and sym.replace("-","").isalpha()):
                    tickers.add(sym)
            log.info(f"  {url.split('/')[-1]}: 누적 {len(tickers)}개")
        except Exception as e: log.error(f"  NASDAQ FTP 실패: {e}")
    result = sorted(tickers)
    log.info(f"미국 전체 {len(result)}종목")
    return result

def get_us_ath(usd_krw: float) -> list:
    tickers = get_us_tickers()
    if not tickers: return []
    log.info(f"미국 {len(tickers)}종목 다운로드...")
    data = batch_download(tickers, period="max", chunk=50)
    cands = find_ath(data)
    log.info(f"미국 후보 {len(cands)}개 → 시가총액")
    out = []
    for c in cands:
        tk = c["ticker"]
        out.append({**c,"name":tk,"price":round(c["price"],2),
                    "mcap":get_mcap(tk,usd_krw,is_kr=False),"market":"US",
                    "url":f"https://m.stock.naver.com/worldstock/stock/{tk}/total"})
    out.sort(key=lambda x: x["gap"], reverse=True)
    log.info(f"미국 최종 {len(out)}종목")
    return out

# ── 한국 전체 종목 ─────────────────────────────────────
def get_kr_tickers() -> list:
    tickers = []
    # 1순위: pykrx
    try:
        from pykrx import stock as pkrx
        today = datetime.now(KST).strftime("%Y%m%d")
        for market,suffix in [("KOSPI",".KS"),("KOSDAQ",".KQ")]:
            try:
                codes = pkrx.get_market_ticker_list(today, market=market)
                for code in codes:
                    try: name=pkrx.get_market_ticker_name(code)
                    except: name=code
                    tickers.append({"code":code,"name":name,"market":market,
                                    "yf":f"{code}{suffix}",
                                    "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                log.info(f"pykrx {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e: log.error(f"pykrx {market}: {e}")
    except Exception as e: log.error(f"pykrx 로드: {e}")
    # 2순위: KRX API
    if not tickers:
        for market,mid,suffix in [("KOSPI","STK",".KS"),("KOSDAQ","KSQ",".KQ")]:
            try:
                r=requests.post("http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    data={"bld":"dbms/MDC/STAT/standard/MDCSTAT01901","mktId":mid,"share":"1","csvxls_isNo":"false"},
                    headers={**HEADERS,"Referer":"http://data.krx.co.kr/"},timeout=30)
                for item in r.json().get("OutBlock_1",[]):
                    code=item.get("ISU_SRT_CD","").strip(); name=item.get("ISU_ABBRV","").strip()
                    if code and name:
                        tickers.append({"code":code,"name":name,"market":market,
                                        "yf":f"{code}{suffix}",
                                        "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                log.info(f"KRX API {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e: log.error(f"KRX API {market}: {e}")
    # 3순위: 네이버 신고가
    if not tickers:
        log.info("네이버 fallback...")
        nh={**HEADERS,"Referer":"https://finance.naver.com/sise/"}
        for sosok,market,suffix in [("0","KOSPI",".KS"),("1","KOSDAQ",".KQ")]:
            for page in range(1,30):
                try:
                    r=requests.get(f"https://finance.naver.com/sise/sise_high.nhn?sosok={sosok}&page={page}",headers=nh,timeout=15)
                    r.encoding="euc-kr"
                    soup=BeautifulSoup(r.text,"html.parser")
                    table=soup.find("table",class_="type_2")
                    if not table: break
                    found=False
                    for row in table.find_all("tr"):
                        cols=row.find_all("td")
                        if len(cols)<4: continue
                        a=cols[0].find("a")
                        if not a: continue
                        href=a.get("href",""); code=href.split("code=")[-1].strip() if "code=" in href else ""
                        name=a.text.strip()
                        if code and name:
                            tickers.append({"code":code,"name":name,"market":market,"yf":f"{code}{suffix}",
                                            "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                            found=True
                    if not found: break
                except: break
    log.info(f"한국 전체 {len(tickers)}종목")
    return tickers

def get_kr_ath(usd_krw: float) -> list:
    all_tk = get_kr_tickers()
    if not all_tk: return []
    yf_codes = [t["yf"] for t in all_tk]
    meta_map = {t["yf"]:t for t in all_tk}
    log.info(f"한국 {len(yf_codes)}종목 다운로드...")
    data = batch_download(yf_codes, period="max", chunk=30)
    cands = find_ath(data)
    log.info(f"한국 후보 {len(cands)}개 → 시가총액")
    out = []
    for c in cands:
        yfc=c["ticker"]; meta=meta_map.get(yfc,{})
        out.append({**c,"ticker":meta.get("code",yfc),"name":meta.get("name",yfc),
                    "price":int(c["price"]),"mcap":get_mcap(yfc,usd_krw,is_kr=True),
                    "market":meta.get("market","KR"),"url":meta.get("url","#")})
    out.sort(key=lambda x: x["gap"], reverse=True)
    log.info(f"한국 최종 {len(out)}종목")
    return out

# ── 이메일 HTML ───────────────────────────────────────
def tbl(stocks, title, currency, holiday, date_s, hmsg=""):
    banner=""
    if holiday and hmsg:
        banner=f'<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 16px;margin-bottom:12px;font-size:13px;color:#856404">⚠️ {hmsg}</div>'
    if not stocks:
        return f"<h2 style='color:#333;margin-top:30px'>{title}</h2><p style='color:#666;font-size:13px'>기준일: {date_s}</p>{banner}<p style='color:#888'>해당 종목 없음</p>"
    fp = lambda p: f"{p:,.2f}" if currency=="USD" else f"{p:,}"
    fm = lambda m: f"{m:,.1f}조" if m else "-"
    rows=""
    for i,s in enumerate(stocks):
        bg="#f9f9f9" if i%2==0 else "#fff"
        cc="#c0392b" if s["change"]>0 else "#2980b9"; cs="+" if s["change"]>0 else ""
        gap=s.get("gap",0); gc="#27ae60" if gap>=-1 else "#e67e22" if gap>=-5 else "#e74c3c"
        link=s.get("url","#")
        rows+=f"""<tr style='background:{bg}'>
          <td style='padding:8px 10px'><a href='{link}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a></td>
          <td style='padding:8px;text-align:center;color:{gc};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right;color:#555;font-size:13px'>{fm(s.get("mcap"))}</td>
          <td style='padding:8px'><a href='{link}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a></td>
          <td style='padding:8px;text-align:right'>{fp(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{cc};font-weight:bold'>{cs}{s['change']}%</td>
        </tr>"""
    return f"""<h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#666;font-size:13px;margin:2px 0 8px'>기준일: {date_s}</p>{banner}
    <p style='color:#aaa;font-size:11px;margin:0 0 10px'>🔗 티커 클릭 → 네이버 증권 | <span style='color:#27ae60'>●</span>0~-1% <span style='color:#e67e22'>●</span>-1~-5% <span style='color:#e74c3c'>●</span>-5~-10%</p>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead><tr style='background:#1a1a2e;color:#fff'>
        <th style='padding:10px;text-align:left'>티커</th><th style='padding:10px;text-align:center'>ATH 괴리율</th>
        <th style='padding:10px;text-align:right'>시가총액</th><th style='padding:10px;text-align:left'>종목명</th>
        <th style='padding:10px;text-align:right'>현재가</th><th style='padding:10px;text-align:right'>등락률</th>
      </tr></thead><tbody>{rows}</tbody></table>"""

def build_email(us, kr, info, usd_krw):
    td = datetime.now(KST).strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:780px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 ATH 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:13px">발송일: {td} | ATH 종가 ~ -10% 이내 | USD/KRW {usd_krw:,.0f}원</p>
  </div>
  <div style="background:#fff;padding:16px 20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08);display:flex;gap:16px;flex-wrap:wrap">
    <div style="background:#eaf4ff;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇺🇸 미국 ({info['us_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
    </div>
    <div style="background:#eaffea;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇰🇷 한국 ({info['kr_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
    </div>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)">
    {tbl(us,"🇺🇸 미국 전체 상장 보통주","USD",info["us_holiday"],info["us_last_str"],info.get("us_holiday_msg",""))}
    <div style="margin-top:36px"></div>
    {tbl(kr,"🇰🇷 한국 KOSPI / KOSDAQ 전체","KRW",info["kr_holiday"],info["kr_last_str"],info.get("kr_holiday_msg",""))}
  </div>
  <p style="font-size:11px;color:#bbb;margin-top:16px;text-align:center">자동 발송 | All Time High 기준 | 투자 권유 아님</p>
</body></html>"""

def build_subject(info):
    ut = " [휴장]" if info["us_holiday"] else ""
    kt = " [휴장]" if info["kr_holiday"] else ""
    return f"📈 ATH 리포트 | 🇺🇸 {info['us_last_str']}{ut} / 🇰🇷 {info['kr_last_str']}{kt}"

def send_email(html, subject):
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

if __name__ == "__main__":
    main()
