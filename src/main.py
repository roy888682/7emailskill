#!/usr/bin/env python3
"""
Daily ATH Stock Email
- 전체 미국 + 전체 한국 종목
- ATH 종가 ~ ATH 종가 -10% 이내
- 괴리율 + 시가총액(조원) 포함
- 직전 거래일 종가 기준 / 휴장 감지
"""

import os, smtplib, logging, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date

import pandas as pd
import pytz
import yfinance as yf
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

KST = pytz.timezone("Asia/Seoul")


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def get_usd_krw() -> float:
    try:
        h = yf.Ticker("USDKRW=X").history(period="5d", auto_adjust=True)
        rate = float(h["Close"].iloc[-1])
        log.info(f"USD/KRW: {rate:,.1f}")
        return rate
    except Exception as e:
        log.warning(f"환율 조회 실패, fallback 1380: {e}")
        return 1380.0


def get_trading_info() -> dict:
    """직전 거래일 및 미국/한국 휴장 여부 확인"""
    yesterday_kst = (datetime.now(KST) - timedelta(days=1)).date()

    def last_trading_date(ticker_str: str) -> date | None:
        try:
            h = yf.Ticker(ticker_str).history(period="7d", auto_adjust=True)
            if h.empty:
                return None
            last = h.index[-1]
            # index가 timezone-aware인 경우 date() 처리
            return last.date() if hasattr(last, "date") else last
        except Exception:
            return None

    us_last = last_trading_date("SPY")
    kr_last = last_trading_date("005930.KS")

    us_holiday = (us_last != yesterday_kst) if us_last else True
    kr_holiday = (kr_last != yesterday_kst) if kr_last else True

    def date_str(d: date | None) -> str:
        if d is None:
            return "확인불가"
        weekday = ["월", "화", "수", "목", "금", "토", "일"][d.weekday()]
        return d.strftime(f"%Y년 %m월 %d일({weekday})")

    log.info(f"미국 직전 거래일: {us_last} (어제={yesterday_kst}, 휴장={us_holiday})")
    log.info(f"한국 직전 거래일: {kr_last} (어제={yesterday_kst}, 휴장={kr_holiday})")

    return {
        "yesterday_kst":  yesterday_kst,
        "us_last":        us_last,
        "kr_last":        kr_last,
        "us_last_str":    date_str(us_last),
        "kr_last_str":    date_str(kr_last),
        "us_holiday":     us_holiday,
        "kr_holiday":     kr_holiday,
    }


def get_mcap_trillion(yf_code: str, usd_krw: float, is_korean: bool = False) -> float | None:
    try:
        info = yf.Ticker(yf_code).fast_info
        mcap = getattr(info, "market_cap", None) or 0
        if mcap <= 0:
            return None
        return round((mcap / 1e12) if is_korean else (mcap * usd_krw / 1e12), 1)
    except Exception:
        return None


def batch_download(tickers: list, period: str, chunk_size: int = 80) -> dict:
    """yfinance 배치 다운로드 — 안정적인 버전 (group_by 미사용)"""
    result = {}
    total = len(tickers)
    n = (total + chunk_size - 1) // chunk_size

    for i in range(0, total, chunk_size):
        chunk = tickers[i:i + chunk_size]
        bn = i // chunk_size + 1
        log.info(f"  배치 [{bn}/{n}] {i+1}~{min(i+chunk_size,total)}/{total}")
        try:
            raw = yf.download(chunk, period=period, progress=False, auto_adjust=True)
            if raw.empty:
                continue

            close = raw.get("Close", None)
            if close is None:
                continue

            if isinstance(close, pd.Series):          # 단일 종목
                close = pd.DataFrame({chunk[0]: close})

            for tk in chunk:
                if tk in close.columns:
                    s = close[tk].dropna()
                    if len(s) >= 20:
                        result[tk] = s
        except Exception as e:
            log.error(f"  배치 [{bn}] 오류: {e}")
        time.sleep(1.2)

    log.info(f"  배치 완료: {len(result)}종목 수집")
    return result


def find_ath_candidates(data: dict, threshold: float = 0.90) -> list[dict]:
    out = []
    for ticker, series in data.items():
        try:
            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            ath  = float(series.max())
            if last >= ath * threshold:
                out.append({
                    "ticker": ticker,
                    "price":  last,
                    "change": round((last - prev) / prev * 100, 2),
                    "ath":    ath,
                    "gap":    round((last - ath) / ath * 100, 2),
                })
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────
# 1. 미국 전체 종목
# ─────────────────────────────────────────────

def get_all_us_tickers() -> list[str]:
    tickers = set()
    specs = [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",  6, 3),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt",   6, 7),
    ]
    for url, etf_col, test_col in specs:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                parts = line.split("|")
                if len(parts) <= max(etf_col, test_col):
                    continue
                sym    = parts[0].strip()
                is_etf = len(parts) > etf_col and parts[etf_col].strip() == "Y"
                is_tst = len(parts) > test_col and parts[test_col].strip() == "Y"
                if sym and not is_etf and not is_tst and sym.replace("-", "").isalpha():
                    tickers.add(sym)
        except Exception as e:
            log.error(f"NASDAQ FTP 실패 ({url}): {e}")

    result = sorted(tickers)
    log.info(f"미국 전체 종목 {len(result)}개")
    return result


def get_us_ath_stocks(usd_krw: float) -> list[dict]:
    tickers = get_all_us_tickers()
    if not tickers:
        log.error("미국 티커 수집 실패")
        return []

    log.info(f"미국 {len(tickers)}종목 다운로드 중...")
    data = batch_download(tickers, period="10y", chunk_size=80)

    candidates = find_ath_candidates(data)
    log.info(f"미국 ATH -10% 이내: {len(candidates)}종목 → 시가총액 조회")

    results = []
    for c in candidates:
        tk = c["ticker"]
        results.append({
            "ticker": tk,
            "name":   tk,
            "price":  round(c["price"], 2),
            "change": c["change"],
            "ath":    round(c["ath"], 2),
            "gap":    c["gap"],
            "mcap":   get_mcap_trillion(tk, usd_krw, is_korean=False),
            "market": "US",
            "url":    f"https://m.stock.naver.com/worldstock/stock/{tk}/total",
        })

    results.sort(key=lambda x: x["gap"], reverse=True)
    log.info(f"미국 최종: {len(results)}종목")
    return results


# ─────────────────────────────────────────────
# 2. 한국 전체 종목
# ─────────────────────────────────────────────

def get_all_korea_tickers() -> list[dict]:
    tickers = []

    # 1순위: pykrx (로그인 없이 티커 리스트 가능)
    try:
        from pykrx import stock as pkrx
        today = datetime.now(KST).strftime("%Y%m%d")
        for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
            try:
                codes = pkrx.get_market_ticker_list(today, market=market)
                for code in codes:
                    try:
                        name = pkrx.get_market_ticker_name(code)
                    except Exception:
                        name = code
                    tickers.append({
                        "code": code, "name": name, "market": market,
                        "yf_code": f"{code}{suffix}",
                        "url": f"https://finance.naver.com/item/main.naver?code={code}",
                    })
                log.info(f"pykrx {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e:
                log.error(f"pykrx {market} 실패: {e}")
    except Exception as e:
        log.error(f"pykrx 로드 실패: {e}")

    # 2순위: KRX API
    if not tickers:
        log.info("KRX API fallback 시도...")
        for market, mkt_id, suffix in [("KOSPI","STK",".KS"),("KOSDAQ","KSQ",".KQ")]:
            try:
                r = requests.post(
                    "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    data={"bld":"dbms/MDC/STAT/standard/MDCSTAT01901","mktId":mkt_id,"share":"1","csvxls_isNo":"false"},
                    headers={**HEADERS, "Referer":"http://data.krx.co.kr/"},
                    timeout=30
                )
                for item in r.json().get("OutBlock_1", []):
                    code = item.get("ISU_SRT_CD","").strip()
                    name = item.get("ISU_ABBRV","").strip()
                    if code and name:
                        tickers.append({"code":code,"name":name,"market":market,
                                        "yf_code":f"{code}{suffix}",
                                        "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                log.info(f"KRX API {market}: {sum(1 for t in tickers if t['market']==market)}종목")
            except Exception as e:
                log.error(f"KRX API {market} 실패: {e}")

    # 3순위: 네이버 신고가 (최소 보장)
    if not tickers:
        log.info("네이버 신고가 fallback 시도...")
        naver_h = {**HEADERS, "Referer":"https://finance.naver.com/sise/"}
        for sosok, market, suffix in [("0","KOSPI",".KS"),("1","KOSDAQ",".KQ")]:
            for page in range(1, 10):
                try:
                    r = requests.get(
                        f"https://finance.naver.com/sise/sise_high.nhn?sosok={sosok}&page={page}",
                        headers=naver_h, timeout=15)
                    r.encoding = "euc-kr"
                    soup = BeautifulSoup(r.text, "html.parser")
                    table = soup.find("table", class_="type_2")
                    if not table:
                        break
                    found = False
                    for row in table.find_all("tr"):
                        cols = row.find_all("td")
                        if len(cols) < 4:
                            continue
                        a = cols[0].find("a")
                        if not a:
                            continue
                        href = a.get("href","")
                        code = href.split("code=")[-1].strip() if "code=" in href else ""
                        name = a.text.strip()
                        if code and name:
                            tickers.append({"code":code,"name":name,"market":market,
                                            "yf_code":f"{code}{suffix}",
                                            "url":f"https://finance.naver.com/item/main.naver?code={code}"})
                            found = True
                    if not found:
                        break
                except Exception:
                    break

    log.info(f"한국 전체 {len(tickers)}종목 수집 완료")
    return tickers


def get_korea_ath_stocks(usd_krw: float) -> list[dict]:
    all_tickers = get_all_korea_tickers()
    if not all_tickers:
        log.error("한국 티커 수집 실패")
        return []

    yf_codes   = [t["yf_code"] for t in all_tickers]
    ticker_map = {t["yf_code"]: t for t in all_tickers}

    log.info(f"한국 {len(yf_codes)}종목 다운로드 중...")
    data = batch_download(yf_codes, period="10y", chunk_size=50)

    candidates = find_ath_candidates(data)
    log.info(f"한국 ATH -10% 이내: {len(candidates)}종목 → 시가총액 조회")

    results = []
    for c in candidates:
        yfc  = c["ticker"]
        meta = ticker_map.get(yfc, {})
        results.append({
            "ticker": meta.get("code", yfc),
            "name":   meta.get("name", yfc),
            "price":  int(c["price"]),
            "change": c["change"],
            "ath":    int(c["ath"]),
            "gap":    c["gap"],
            "mcap":   get_mcap_trillion(yfc, usd_krw, is_korean=True),
            "market": meta.get("market","KR"),
            "url":    meta.get("url","#"),
        })

    results.sort(key=lambda x: x["gap"], reverse=True)
    log.info(f"한국 최종: {len(results)}종목")
    return results


# ─────────────────────────────────────────────
# 3. 이메일 HTML
# ─────────────────────────────────────────────

def _table_html(stocks: list, title: str, currency: str,
                holiday: bool, last_date_str: str) -> str:
    holiday_banner = ""
    if holiday:
        holiday_banner = f"""
        <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;
                    padding:10px 16px;margin-bottom:12px;font-size:13px;color:#856404">
          ⚠️ 직전 영업일 기준 데이터입니다. 어제는 <b>휴장</b>이었습니다.
        </div>"""

    if not stocks:
        return f"""
        <h2 style='color:#333;margin-top:30px'>{title}</h2>
        <p style='color:#666;font-size:13px'>기준일: {last_date_str}</p>
        {holiday_banner}
        <p style='color:#888'>해당 종목 없음</p>"""

    def fmt(p):
        return f"{p:,.2f}" if currency == "USD" else f"{p:,}"

    rows = ""
    for i, s in enumerate(stocks):
        bg        = "#f9f9f9" if i % 2 == 0 else "#fff"
        c_color   = "#c0392b" if s["change"] > 0 else "#2980b9"
        c_sign    = "+" if s["change"] > 0 else ""
        gap       = s.get("gap", 0.0)
        gap_color = "#27ae60" if gap >= -1 else "#e67e22" if gap >= -5 else "#e74c3c"
        link      = s.get("url", "#")
        mcap_str  = f"{s['mcap']:,.1f}조" if s.get("mcap") else "-"

        rows += f"""
        <tr style='background:{bg}'>
          <td style='padding:8px 10px'>
            <a href='{link}' target='_blank'
               style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a>
          </td>
          <td style='padding:8px;text-align:center;color:{gap_color};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right;color:#555;font-size:13px'>{mcap_str}</td>
          <td style='padding:8px'>
            <a href='{link}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a>
          </td>
          <td style='padding:8px;text-align:right'>{fmt(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{c_color};font-weight:bold'>{c_sign}{s['change']}%</td>
        </tr>"""

    return f"""
    <h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#666;font-size:13px;margin:2px 0 8px'>기준일: {last_date_str}</p>
    {holiday_banner}
    <p style='color:#aaa;font-size:11px;margin:0 0 10px'>
      🔗 티커 클릭 → 네이버 증권 &nbsp;|&nbsp;
      <span style='color:#27ae60'>●</span>0~-1%
      <span style='color:#e67e22'>●</span>-1~-5%
      <span style='color:#e74c3c'>●</span>-5~-10%
    </p>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead>
        <tr style='background:#1a1a2e;color:#fff'>
          <th style='padding:10px;text-align:left'>티커</th>
          <th style='padding:10px;text-align:center'>ATH 괴리율</th>
          <th style='padding:10px;text-align:right'>시가총액</th>
          <th style='padding:10px;text-align:left'>종목명</th>
          <th style='padding:10px;text-align:right'>현재가</th>
          <th style='padding:10px;text-align:right'>등락률</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def build_html_email(us: list, kr: list, info: dict, usd_krw: float) -> str:
    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:780px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 ATH 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:13px">
      발송일: {today_str} &nbsp;|&nbsp;
      ATH 종가 ~ ATH 종가 -10% 이내 &nbsp;|&nbsp;
      USD/KRW {usd_krw:,.0f}원
    </p>
  </div>

  <div style="background:#fff;padding:16px 20px;border-radius:8px;margin-top:12px;
              box-shadow:0 1px 4px rgba(0,0,0,0.08);display:flex;gap:16px;flex-wrap:wrap">
    <div style="background:#eaf4ff;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇺🇸 미국 ATH ({info['us_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
    </div>
    <div style="background:#eaffea;border-radius:6px;padding:10px 20px">
      <div style="font-size:11px;color:#555">🇰🇷 한국 ATH ({info['kr_last_str']})</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
    </div>
  </div>

  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;
              box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    {_table_html(us,"🇺🇸 미국 전체 상장 보통주","USD",info["us_holiday"],info["us_last_str"])}
    <div style="margin-top:36px"></div>
    {_table_html(kr,"🇰🇷 한국 KOSPI / KOSDAQ 전체","KRW",info["kr_holiday"],info["kr_last_str"])}
  </div>

  <p style="font-size:11px;color:#bbb;margin-top:16px;text-align:center">
    자동 발송 | 10년 고가 기준 ATH | 투자 권유 아님
  </p>
</body></html>"""


# ─────────────────────────────────────────────
# 4. 이메일 발송
# ─────────────────────────────────────────────

def build_subject(info: dict) -> str:
    """거래일 포함 + 휴장 여부 표시 제목"""
    us_str = info["us_last_str"]
    kr_str = info["kr_last_str"]
    us_tag = " [미국 휴장]" if info["us_holiday"] else ""
    kr_tag = " [한국 휴장]" if info["kr_holiday"] else ""
    return f"📈 ATH 리포트 | 미국 {us_str}{us_tag} / 한국 {kr_str}{kr_tag}"


def send_email(html: str, subject: str) -> None:
    user      = os.environ["GMAIL_USER"]
    pwd       = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", "ykhan@dacpole.com")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, pwd)
        server.sendmail(user, recipient, msg.as_string())

    log.info(f"✅ 이메일 발송 완료 → {recipient}")
    log.info(f"   제목: {subject}")


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    log.info("=== 일일 ATH 리포트 시작 ===")

    trading_info = get_trading_info()
    usd_krw      = get_usd_krw()
    us_stocks    = get_us_ath_stocks(usd_krw)
    kr_stocks    = get_korea_ath_stocks(usd_krw)

    html    = build_html_email(us_stocks, kr_stocks, trading_info, usd_krw)
    subject = build_subject(trading_info)
    send_email(html, subject)

    log.info(f"=== 완료: 미국 {len(us_stocks)}종목 / 한국 {len(kr_stocks)}종목 ===")


if __name__ == "__main__":
    main()
