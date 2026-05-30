#!/usr/bin/env python3
"""
Daily ATH Stock Email — 전체 미국 + 전체 한국 종목 버전
ATH 종가 ~ ATH 종가 -10% 이내 종목 | 괴리율 + 시가총액(조원) 포함
"""

import os, smtplib, logging, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import yfinance as yf
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def get_usd_krw() -> float:
    """당일 USD/KRW 환율 조회"""
    try:
        hist = yf.Ticker("USDKRW=X").history(period="5d")
        rate = float(hist["Close"].iloc[-1])
        log.info(f"USD/KRW 환율: {rate:,.1f}")
        return rate
    except Exception as e:
        log.error(f"환율 조회 실패: {e}")
        return 1380.0  # fallback


def get_mcap_trillion(yf_code: str, usd_krw: float, is_korean: bool = False) -> float | None:
    """yfinance에서 시가총액 조회 → 조원 단위 반환"""
    try:
        info = yf.Ticker(yf_code).fast_info
        mcap = getattr(info, "market_cap", None)
        if not mcap or mcap <= 0:
            return None
        if is_korean:
            return round(mcap / 1e12, 1)
        else:
            return round(mcap * usd_krw / 1e12, 1)
    except Exception:
        return None


def batch_download(tickers: list, period: str, chunk_size: int = 80) -> dict:
    """yfinance 배치 다운로드 → {ticker: Series(Close)} 딕셔너리 반환"""
    result = {}
    total = len(tickers)
    for i in range(0, total, chunk_size):
        chunk = tickers[i:i + chunk_size]
        log.info(f"  다운로드 중 {i+1}~{min(i+chunk_size, total)} / {total}")
        try:
            raw = yf.download(chunk, period=period, progress=False,
                              auto_adjust=True, group_by="ticker")
            for tk in chunk:
                try:
                    s = (raw[tk]["Close"] if len(chunk) > 1 else raw["Close"]).dropna()
                    if len(s) >= 20:
                        result[tk] = s
                except Exception:
                    pass
        except Exception as e:
            log.error(f"배치 오류 (idx {i}): {e}")
        time.sleep(0.3)
    return result


def find_ath_candidates(data: dict, threshold: float = 0.90) -> list[dict]:
    """다운로드 데이터에서 ATH -10% 이내 종목 추출"""
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
    """NASDAQ FTP에서 전체 미국 상장 보통주 코드 수집"""
    tickers = set()

    for url, etf_col, test_col in [
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt",  3, 5),
        ("https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt",   6, 7),
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            for line in r.text.strip().split("\n")[1:-1]:
                parts = line.split("|")
                if len(parts) <= max(etf_col, test_col):
                    continue
                sym    = parts[0].strip()
                is_etf = parts[etf_col].strip() == "Y"
                is_tst = parts[test_col].strip() == "Y"
                if sym and not is_etf and not is_tst and sym.replace("-", "").isalpha():
                    tickers.add(sym)
        except Exception as e:
            log.error(f"미국 티커 수집 실패 ({url}): {e}")

    result = sorted(tickers)
    log.info(f"미국 전체 종목 {len(result)}개 수집")
    return result


def get_us_ath_stocks(usd_krw: float) -> list[dict]:
    tickers = get_all_us_tickers()
    log.info(f"미국 {len(tickers)}종목 10년 데이터 다운로드 중...")

    data = batch_download(tickers, period="10y", chunk_size=80)
    log.info(f"다운로드 완료: {len(data)}종목")

    candidates = find_ath_candidates(data)
    log.info(f"ATH -10% 이내 후보: {len(candidates)}종목 → 시가총액 조회 중...")

    results = []
    for c in candidates:
        tk = c["ticker"]
        mcap = get_mcap_trillion(tk, usd_krw, is_korean=False)
        results.append({
            "ticker": tk,
            "name":   tk,
            "price":  round(c["price"], 2),
            "change": c["change"],
            "ath":    round(c["ath"], 2),
            "gap":    c["gap"],
            "mcap":   mcap,
            "market": "US",
            "url":    f"https://m.stock.naver.com/worldstock/stock/{tk}/total",
        })

    log.info(f"미국 ATH 최종 {len(results)}종목")
    return sorted(results, key=lambda x: x["gap"], reverse=True)  # 괴리율 낮은 순


# ─────────────────────────────────────────────
# 2. 한국 전체 종목
# ─────────────────────────────────────────────

def get_all_korea_tickers() -> list[dict]:
    """KRX API에서 전체 KOSPI/KOSDAQ 종목 수집"""
    tickers = []

    for market_name, mkt_id in [("KOSPI", "STK"), ("KOSDAQ", "KSQ")]:
        try:
            r = requests.post(
                "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                data={
                    "bld": "dbms/MDC/STAT/standard/MDCSTAT01901",
                    "mktId": mkt_id,
                    "share": "1",
                    "csvxls_isNo": "false",
                },
                headers={**HEADERS, "Referer": "http://data.krx.co.kr/"},
                timeout=30,
            )
            suffix = ".KS" if market_name == "KOSPI" else ".KQ"
            for item in r.json().get("OutBlock_1", []):
                code = item.get("ISU_SRT_CD", "").strip()
                name = item.get("ISU_ABBRV", "").strip()
                if code and name:
                    tickers.append({
                        "code":    code,
                        "name":    name,
                        "market":  market_name,
                        "yf_code": f"{code}{suffix}",
                        "url":     f"https://finance.naver.com/item/main.naver?code={code}",
                    })
        except Exception as e:
            log.error(f"KRX {market_name} 수집 실패: {e}")

    log.info(f"한국 전체 종목 {len(tickers)}개 수집")
    return tickers


def _naver_fallback_tickers() -> list[dict]:
    """KRX API 실패 시 네이버 금융 신고가 후보로 대체"""
    candidates = []
    naver_h = {**HEADERS, "Referer": "https://finance.naver.com/sise/"}
    for sosok, market, suffix in [("0","KOSPI",".KS"), ("1","KOSDAQ",".KQ")]:
        for page in range(1, 8):
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
                    href = a.get("href", "")
                    code = href.split("code=")[-1].strip() if "code=" in href else ""
                    name = a.text.strip()
                    price_raw = cols[1].text.strip().replace(",", "")
                    if code and name and price_raw.isdigit():
                        candidates.append({
                            "code": code, "name": name, "market": market,
                            "yf_code": f"{code}{suffix}",
                            "url": f"https://finance.naver.com/item/main.naver?code={code}",
                        })
                        found = True
                if not found:
                    break
            except Exception:
                break
    return candidates


def get_korea_ath_stocks(usd_krw: float) -> list[dict]:
    all_tickers = get_all_korea_tickers()
    if not all_tickers:
        log.warning("KRX API 실패 → 네이버 신고가 페이지 fallback 사용")
        all_tickers = _naver_fallback_tickers()

    yf_codes  = [t["yf_code"] for t in all_tickers]
    ticker_map = {t["yf_code"]: t for t in all_tickers}

    log.info(f"한국 {len(yf_codes)}종목 10년 데이터 다운로드 중...")
    data = batch_download(yf_codes, period="10y", chunk_size=50)
    log.info(f"다운로드 완료: {len(data)}종목")

    candidates = find_ath_candidates(data)
    log.info(f"ATH -10% 이내 후보: {len(candidates)}종목 → 시가총액 조회 중...")

    results = []
    for c in candidates:
        yf_code = c["ticker"]
        meta    = ticker_map.get(yf_code, {})
        mcap    = get_mcap_trillion(yf_code, usd_krw, is_korean=True)
        results.append({
            "ticker": meta.get("code", yf_code),
            "name":   meta.get("name", yf_code),
            "price":  int(c["price"]),
            "change": c["change"],
            "ath":    int(c["ath"]),
            "gap":    c["gap"],
            "mcap":   mcap,
            "market": meta.get("market", "KR"),
            "url":    meta.get("url", "#"),
        })

    log.info(f"한국 ATH 최종 {len(results)}종목")
    return sorted(results, key=lambda x: x["gap"], reverse=True)


# ─────────────────────────────────────────────
# 3. 이메일 HTML
# ─────────────────────────────────────────────

def _table_html(stocks: list, title: str, currency: str) -> str:
    if not stocks:
        return f"<h2 style='color:#333'>{title}</h2><p style='color:#888'>오늘 해당 종목 없음</p>"

    def fmt_price(p):
        return f"{p:,.2f}" if currency == "USD" else f"{p:,}"

    def fmt_mcap(m):
        if m is None:
            return "-"
        return f"{m:,.1f}조"

    rows = ""
    for i, s in enumerate(stocks):
        bg         = "#f9f9f9" if i % 2 == 0 else "#fff"
        chg_color  = "#c0392b" if s["change"] > 0 else "#2980b9"
        chg_sign   = "+" if s["change"] > 0 else ""
        gap        = s.get("gap", 0.0)
        gap_color  = "#27ae60" if gap >= -1 else "#e67e22" if gap >= -5 else "#e74c3c"
        link       = s.get("url", "#")
        mcap_str   = fmt_mcap(s.get("mcap"))

        rows += f"""
        <tr style='background:{bg}'>
          <td style='padding:8px'>
            <a href='{link}' target='_blank' style='color:#1565c0;font-weight:bold;text-decoration:none'>{s['ticker']}</a>
          </td>
          <td style='padding:8px;text-align:center;color:{gap_color};font-weight:bold'>{gap:+.1f}%</td>
          <td style='padding:8px;text-align:right;color:#555;font-size:13px'>{mcap_str}</td>
          <td style='padding:8px'>
            <a href='{link}' target='_blank' style='color:#333;text-decoration:none'>{s['name']}</a>
          </td>
          <td style='padding:8px;text-align:right'>{fmt_price(s['price'])} {currency}</td>
          <td style='padding:8px;text-align:right;color:{chg_color};font-weight:bold'>{chg_sign}{s['change']}%</td>
        </tr>"""

    return f"""
    <h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#888;font-size:12px;margin:4px 0 12px'>
      티커 클릭 → 네이버 증권 차트 |
      <span style='color:#27ae60'>●</span> ATH 근접 &nbsp;
      <span style='color:#e67e22'>●</span> -1~-5% &nbsp;
      <span style='color:#e74c3c'>●</span> -5~-10%
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


def build_html_email(us: list, kr: list, usd_krw: float) -> str:
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:760px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 ATH 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:14px">
      {today_str} | ATH 종가 ~ ATH 종가 -10% 이내 종목 | USD/KRW {usd_krw:,.0f}원
    </p>
  </div>
  <div style="background:#fff;padding:16px 20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,0.08);display:flex;gap:16px;flex-wrap:wrap">
    <div style="background:#eaf4ff;border-radius:6px;padding:10px 20px">
      <div style="font-size:12px;color:#555">🇺🇸 미국 ATH</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
    </div>
    <div style="background:#eaffea;border-radius:6px;padding:10px 20px">
      <div style="font-size:12px;color:#555">🇰🇷 한국 ATH</div>
      <div style="font-size:26px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
    </div>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    {_table_html(us, "🇺🇸 미국 전체 상장 보통주", "USD")}
    <div style="margin-top:32px"></div>
    {_table_html(kr, "🇰🇷 한국 KOSPI / KOSDAQ 전체", "KRW")}
  </div>
  <p style="font-size:11px;color:#aaa;margin-top:16px;text-align:center">
    자동 발송 | 10년 고가 기준 ATH | 투자 권유 아님
  </p>
</body></html>"""


# ─────────────────────────────────────────────
# 4. 이메일 발송
# ─────────────────────────────────────────────

def send_email(html: str) -> None:
    user      = os.environ["GMAIL_USER"]
    pwd       = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", "ykhan@dacpole.com")
    today_str = datetime.now().strftime("%Y-%m-%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 ATH 리포트 {today_str}"
    msg["From"]    = user
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, pwd)
        server.sendmail(user, recipient, msg.as_string())

    log.info(f"✅ 이메일 발송 완료 → {recipient}")


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    log.info("=== 일일 ATH 리포트 시작 ===")

    usd_krw = get_usd_krw()
    us      = get_us_ath_stocks(usd_krw)
    kr      = get_korea_ath_stocks(usd_krw)

    html = build_html_email(us, kr, usd_krw)
    send_email(html)

    log.info(f"=== 완료: 미국 {len(us)}종목 / 한국 {len(kr)}종목 ===")


if __name__ == "__main__":
    main()
