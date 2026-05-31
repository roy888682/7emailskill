#!/usr/bin/env python3
import os, smtplib, logging, time, io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
import pytz, yfinance as yf, requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
UA  = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0","Accept-Language":"ko-KR,ko;q=0.9"}

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
            h=yf.Ticker(sym).history(period="10d",auto_adjust=True)
            if h.empty: return None
            last=h.index[-1]; return last.date() if hasattr(last,"date") else last
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

# ── US: 2단계 (1년 스크리닝 → max ATH 검증) ──────────
def get_us_mcap(tk, usd_krw):
    try:
        m=getattr(yf.Ticker(tk).fast_info,"market_cap",None) or 0
        return round(m*usd_krw/1e12,1) if m>0 else None
    except: return None

def dl(tickers, period, chunk=80, sleep=1.2):
    out={}; n=len(tickers)
    if not n: return out
    for i in range(0,n,chunk):
        grp=tickers[i:i+chunk]; bn=i//chunk+1
        log.info(f"  [{bn}/{(n+chunk-1)//chunk}] {i+1}~{min(i+chunk,n)}/{n} ({period})")
        try:
            raw=yf.download(grp,period=period,progress=False,auto_adjust=True,group_by="ticker")
            if raw.empty: time.sleep(sleep); continue
            for tk in grp:
                try:
                    s=(raw[tk]["Close"] if len(grp)>1 else raw["Close"]).dropna()
                    if len(s)>=10: out[tk]=s
                except: pass
        except Exception as e: log.error(f"  [{bn}] {e}")
        time.sleep(sleep)
    log.info(f"  완료:{len(out)}/{n}"); return out

def get_us_tickers():
    tickers=set()
    for url,ec,tc in [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",6,3),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt", 6,7),
    ]:
        try:
            r=requests.get(url,headers=UA,timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                p=line.split("|")
                if len(p)<=max(ec,tc): continue
                sym=p[0].strip()
                if sym and not(len(p)>ec and p[ec].strip()=="Y") and not(len(p)>tc and p[tc].strip()=="Y") and sym.replace("-","").isalpha():
                    tickers.add(sym)
            log.info(f"  FTP {url.split('/')[-1]}:{len(tickers)}")
        except Exception as e: log.error(f"  FTP실패:{e}")
    if len(tickers)<100:
        try:
            import pandas as pd
            r=requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",headers=UA,timeout=20)
            df=pd.read_html(io.StringIO(r.text))[0]
            for s in df["Symbol"].tolist(): tickers.add(str(s).replace(".","-"))
            log.info(f"  Wikipedia S&P500 fallback:{len(tickers)}")
        except Exception as e: log.error(f"  Wikipedia:{e}")
    result=sorted(tickers); log.info(f"미국 {len(result)}종목"); return result

def get_us_ath(usd_krw):
    tickers=get_us_tickers()
    if not tickers: return []
    log.info(f"미국 1단계: {len(tickers)}종목 1년 스크리닝")
    d1=dl(tickers,"1y",chunk=100,sleep=1.0)
    cands=[tk for tk,s in d1.items() if len(s)>=2 and float(s.iloc[-1])>=float(s.max())*0.90]
    log.info(f"미국 1단계 후보:{len(cands)} → 2단계 max ATH")
    if not cands: return []
    d2=dl(cands,"max",chunk=25,sleep=2.0)
    out=[]
    for tk,s in d2.items():
        try:
            last=float(s.iloc[-1]); prev=float(s.iloc[-2]); ath=float(s.max())
            if last>=ath*0.90:
                out.append({"ticker":tk,"name":tk,"price":round(last,2),
                            "change":round((last-prev)/prev*100,2),
                            "gap":round((last-ath)/ath*100,2),
                            "mcap":get_us_mcap(tk,usd_krw),"market":"US",
                            "url":f"https://m.stock.naver.com/worldstock/stock/{tk}/total"})
        except: pass
    out.sort(key=lambda x:x["gap"])  # -10%부터 위로
    log.info(f"미국 최종:{len(out)}"); return out

# ── 한국: pykrx 월별 벌크 방식 (yfinance 비사용) ────────
def get_kr_ath(usd_krw):
    try:
        from pykrx import stock as pk
    except:
        log.error("pykrx 없음"); return []

    today=datetime.now(KST); today_str=today.strftime("%Y%m%d")
    yest_str=prev_weekday(today.date()).strftime("%Y%m%d")
    results=[]

    for market in ["KOSPI","KOSDAQ"]:
        log.info(f"한국 {market} 처리 중...")

        # 오늘 + 어제 시세
        try:
            df_today=pk.get_market_ohlcv_by_ticker(today_str,market=market)
            df_yest =pk.get_market_ohlcv_by_ticker(yest_str, market=market)
        except Exception as e:
            log.error(f"  {market} 오늘/어제 데이터 실패:{e}"); continue

        if df_today is None or df_today.empty:
            log.warning(f"  {market} 오늘 데이터 없음"); continue

        # 5년 월별 ATH 데이터 (60개월)
        log.info(f"  {market} 5년 월별 ATH 수집...")
        ath_map={}  # {code: max_price}
        for months_back in range(0,61):
            d=(today-timedelta(days=30*months_back)).strftime("%Y%m%d")
            try:
                df_m=pk.get_market_ohlcv_by_ticker(d,market=market)
                if df_m is None or df_m.empty: continue
                col="종가" if "종가" in df_m.columns else df_m.columns[3]
                for code in df_m.index:
                    p=float(df_m.loc[code,col])
                    if p>0: ath_map[code]=max(ath_map.get(code,0),p)
            except: pass

        # 시가총액
        mcap_map={}
        try:
            df_cap=pk.get_market_cap_by_ticker(today_str,market=market)
            if df_cap is not None and not df_cap.empty:
                col="시가총액" if "시가총액" in df_cap.columns else df_cap.columns[0]
                for code in df_cap.index:
                    v=float(df_cap.loc[code,col])
                    if v>0: mcap_map[code]=round(v/1e12,1)
        except Exception as e: log.warning(f"  시가총액:{e}")

        close_col="종가" if "종가" in df_today.columns else df_today.columns[3]

        # ATH 필터링
        for code in df_today.index:
            try:
                last=float(df_today.loc[code,close_col])
                if last<=0: continue
                prev=float(df_yest.loc[code,close_col]) if (df_yest is not None and code in df_yest.index) else last
                ath=max(ath_map.get(code,last),last)
                if ath<=0: continue
                gap=(last-ath)/ath*100
                if last>=ath*0.90:
                    try: name=pk.get_market_ticker_name(code)
                    except: name=code
                    results.append({"ticker":code,"name":name,"price":int(last),
                        "change":round((last-prev)/prev*100,2) if prev>0 else 0,
                        "gap":round(gap,2),"mcap":mcap_map.get(code),
                        "market":market,"url":f"https://finance.naver.com/item/main.naver?code={code}"})
            except: continue

    results.sort(key=lambda x:x["gap"])  # -10%부터 위로
    log.info(f"한국 최종:{len(results)}"); return results

# ── 이메일 ────────────────────────────────────────────
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
        gap=s.get("gap",0); gc="#e74c3c" if gap<=-5 else "#e67e22" if gap<=-1 else "#27ae60"
        lk=s.get("url","#")
        rows+=f"""<tr style='background:{bg}'>
          <td style='padding:8px 10px'><a href='{lk}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a></td>
          <td style='padding:8px;text-align:center;color:{gc};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right;color:#555;font-size:13px'>{fm(s.get("mcap"))}</td>
          <td style='padding:8px'><a href='{lk}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a></td>
          <td style='padding:8px;text-align:right'>{fp(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{cc};font-weight:bold'>{cs}{s['change']}%</td></tr>"""
    return f"""<h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#666;font-size:13px;margin:2px 0 8px'>기준일:{date_s} | 괴리율 -10%에 가까운 순</p>{banner}
    <p style='color:#aaa;font-size:11px;margin:0 0 10px'>🔗 티커 클릭→네이버 증권 | <span style='color:#e74c3c'>●</span>-5~-10% <span style='color:#e67e22'>●</span>-1~-5% <span style='color:#27ae60'>●</span>0~-1%</p>
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
    <p style="margin:6px 0 0;opacity:0.7;font-size:13px">발송일:{td} | ATH ~ -10% | USD/KRW {usd_krw:,.0f}원</p>
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
    us=get_us_ath(usd_krw); kr=get_kr_ath(usd_krw)
    send_email(build_email(us,kr,info,usd_krw),build_subject(info))
    log.info(f"=== 완료: US{len(us)} KR{len(kr)} ===")

if __name__=="__main__": main()

