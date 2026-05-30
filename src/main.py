#!/usr/bin/env python3
"""
Daily ATH Stock Email — True All-Time High 버전
미국(S&P 500) + 한국(KOSPI/KOSDAQ) 진짜 역대 최고가 종목을 매일 이메일로 발송
"""

import os, smtplib, logging
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

SP500_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","BRK-B","AVGO",
    "JPM","LLY","V","UNH","XOM","MA","JNJ","PG","HD","COST","MRK","ABBV",
    "CVX","CRM","BAC","NFLX","AMD","PEP","KO","TMO","WMT","ORCL","CSCO",
    "ACN","MCD","ABT","ADBE","LIN","DHR","NEE","TXN","PM","QCOM","WFC","IBM",
    "INTU","GE","SPGI","RTX","CAT","AMGN","ISRG","AXP","CMCSA","BX","LOW",
    "VRTX","GS","SYK","BKNG","T","TJX","SCHW","UBER","MDT","ELV","PLD","BSX",
    "REGN","CB","ADI","DE","MU","LRCX","AMAT","KLAC","PANW","SO","ADP","DUK",
    "CI","MO","SHW","ZTS","PGR","USB","MMC","MDLZ","TGT","EOG","HUM","ITW",
    "NOC","HCA","CDNS","SNPS","MCO","CME","FDX","CL","APD","ICE","ETN","AON",
]


# ─────────────────────────────────────────────
# 1. 미국 — 역대 ATH 종목
# ─────────────────────────────────────────────

def get_us_ath_stocks() -> list[dict]:
    log.info(f"미국 {len(SP500_TICKERS)}종목 전체 히스토리 다운로드 중...")
    try:
        raw = yf.download(
            SP500_TICKERS, period="max", progress=False,
            auto_adjust=True, group_by="ticker"
        )
    except Exception as e:
        log.error(f"yfinance 오류: {e}")
        return []

    results = []
    for ticker in SP500_TICKERS:
        try:
            try:
                series = raw[ticker]["Close"].dropna()
            except KeyError:
                series = raw["Close"].dropna()

            if len(series) < 50:
                continue

            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            ath  = float(series.max())

            if last >= ath * 0.995:   # 역대 최고가의 99.5% 이상
                results.append({
                    "ticker": ticker,
                    "name":   ticker,
                    "price":  round(last, 2),
                    "change": round((last - prev) / prev * 100, 2),
                    "ath":    round(ath, 2),
                    "market": "US",
                    "url":    f"https://m.stock.naver.com/worldstock/stock/{ticker}/total",
                })
        except Exception:
            continue

    log.info(f"미국 ATH {len(results)}종목 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 2. 한국 — 네이버 신고가 → 역대 ATH 검증
# ─────────────────────────────────────────────

def _scrape_naver_candidates(sosok: str, market: str) -> list[dict]:
    """네이버 금융 신고가 페이지에서 종목 코드·이름 추출"""
    candidates = []
    naver_headers = {**HEADERS, "Referer": "https://finance.naver.com/sise/"}
    suffix = ".KS" if sosok == "0" else ".KQ"

    for page in range(1, 8):
        url = f"https://finance.naver.com/sise/sise_high.nhn?sosok={sosok}&page={page}"
        try:
            r = requests.get(url, headers=naver_headers, timeout=15)
            r.encoding = "euc-kr"
            soup = BeautifulSoup(r.text, "html.parser")

            table = soup.find("table", class_="type_2")
            if not table:
                break

            has_data = False
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue

                name_tag = cols[0].find("a")
                if not name_tag:
                    continue

                href = name_tag.get("href", "")
                code = href.split("code=")[-1].strip() if "code=" in href else ""
                name = name_tag.text.strip()
                price_raw = cols[1].text.strip().replace(",", "").replace(" ", "")
                pct_raw   = cols[3].text.strip().replace("%","").replace("+","").replace(" ","").replace("\xa0","")

                if not code or not name or not price_raw.isdigit():
                    continue

                try:
                    candidates.append({
                        "code":    code,
                        "name":    name,
                        "price":   int(price_raw),
                        "change":  float(pct_raw) if pct_raw else 0.0,
                        "market":  market,
                        "yf_code": f"{code}{suffix}",
                        "url":     f"https://finance.naver.com/item/main.naver?code={code}",
                    })
                    has_data = True
                except Exception:
                    continue

            if not has_data:
                break

        except Exception as e:
            log.error(f"네이버 스크래핑 오류 ({market} p{page}): {e}")
            break

    return candidates


def _verify_ath(candidates: list[dict]) -> list[dict]:
    """yfinance로 전체 히스토리 조회 → 진짜 역대 ATH만 필터"""
    ath_stocks = []
    for s in candidates:
        try:
            hist = yf.Ticker(s["yf_code"]).history(period="max", auto_adjust=True)
            if hist.empty or len(hist) < 50:
                continue

            last = float(hist["Close"].iloc[-1])
            ath  = float(hist["Close"].max())

            if last >= ath * 0.995:
                ath_stocks.append({
                    "ticker": s["code"],
                    "name":   s["name"],
                    "price":  s["price"],
                    "change": s["change"],
                    "ath":    int(ath),
                    "market": s["market"],
                    "url":    s["url"],
                })
        except Exception:
            continue
    return ath_stocks


def get_korea_ath_stocks() -> list[dict]:
    log.info("한국 신고가 후보 수집 중 (네이버 금융)...")
    candidates  = _scrape_naver_candidates("0", "KOSPI")
    candidates += _scrape_naver_candidates("1", "KOSDAQ")
    log.info(f"후보 {len(candidates)}종목 → 역대 ATH 검증 중...")

    results = _verify_ath(candidates)
    log.info(f"한국 ATH {len(results)}종목 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 3. 이메일 HTML (티커 클릭 → 네이버 증권)
# ─────────────────────────────────────────────

def _table_html(stocks: list, title: str, currency: str) -> str:
    if not stocks:
        return f"<h2 style='color:#333'>{title}</h2><p style='color:#888'>오늘 역대 신고가 종목 없음</p>"

    def fmt(p):
        return f"{p:,.2f}" if currency == "USD" else f"{p:,}"

    rows = ""
    for i, s in enumerate(stocks):
        bg    = "#f9f9f9" if i % 2 == 0 else "#ffffff"
        color = "#c0392b" if s["change"] > 0 else "#2980b9"
        sign  = "+" if s["change"] > 0 else ""
        link  = s.get("url", "#")

        rows += f"""
        <tr style='background:{bg}'>
          <td style='padding:9px'>
            <a href='{link}' target='_blank'
               style='color:#1565c0;font-weight:bold;text-decoration:none'>
              {s['ticker']}
            </a>
          </td>
          <td style='padding:9px'>
            <a href='{link}' target='_blank'
               style='color:#333;text-decoration:none'>
              {s['name']}
            </a>
          </td>
          <td style='padding:9px;text-align:right'>{fmt(s['price'])} {currency}</td>
          <td style='padding:9px;text-align:right;color:{color};font-weight:bold'>{sign}{s['change']}%</td>
        </tr>"""

    return f"""
    <h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <p style='color:#888;font-size:12px;margin:4px 0 12px'>티커/종목명 클릭 시 네이버 증권 차트로 이동</p>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead>
        <tr style='background:#1a1a2e;color:#fff'>
          <th style='padding:10px;text-align:left'>티커</th>
          <th style='padding:10px;text-align:left'>종목명</th>
          <th style='padding:10px;text-align:right'>현재가</th>
          <th style='padding:10px;text-align:right'>등락률</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def build_html_email(us: list, kr: list) -> str:
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:720px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 역대 신고가(ATH) 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:14px">{today_str} | 역대 최고가(±0.5%) 달성 종목</p>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    <span style="background:#eaf4ff;border-radius:6px;padding:10px 20px;margin-right:12px;display:inline-block">
      <div style="font-size:12px;color:#555">미국 ATH</div>
      <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
    </span>
    <span style="background:#eaffea;border-radius:6px;padding:10px 20px;display:inline-block">
      <div style="font-size:12px;color:#555">한국 ATH</div>
      <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
    </span>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    {_table_html(us, "🇺🇸 미국 S&P 500 (주요 100종목)", "USD")}
    <div style="margin-top:32px"></div>
    {_table_html(kr, "🇰🇷 한국 KOSPI / KOSDAQ", "KRW")}
  </div>
  <p style="font-size:11px;color:#aaa;margin-top:20px;text-align:center">
    자동 발송 | 역대 최고가 기준 | 투자 권유 아님
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
    msg["Subject"] = f"📈 역대 ATH 리포트 {today_str}"
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
    log.info("=== 일일 역대 ATH 리포트 시작 ===")
    us   = get_us_ath_stocks()
    kr   = get_korea_ath_stocks()
    html = build_html_email(us, kr)
    send_email(html)
    log.info(f"=== 완료: 미국 {len(us)}종목 / 한국 {len(kr)}종목 ===")

if __name__ == "__main__":
    main()
