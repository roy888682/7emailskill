#!/usr/bin/env python3
"""
Daily ATH Stock Email
미국(S&P 500) + 한국(KOSPI/KOSDAQ) 52주 신고가 종목을 매일 이메일로 발송
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. 미국 — S&P 500 신고가 종목
# ─────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    """위키피디아에서 S&P 500 종목 리스트 반환"""
    df = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    )[0]
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


def get_us_ath_stocks() -> list[dict]:
    """S&P 500 중 52주 신고가(±0.5%) 달성 종목 반환"""
    tickers = get_sp500_tickers()
    start = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")

    log.info(f"yfinance 배치 다운로드 시작 — {len(tickers)}종목")
    raw = yf.download(
        tickers,
        start=start,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )

    results = []
    for ticker in tickers:
        try:
            # group_by='ticker' → raw[ticker]['Close']
            try:
                series = raw[ticker]["Close"].dropna()
            except KeyError:
                series = raw["Close"].dropna()          # 단일 종목 예외처리

            if len(series) < 10:
                continue

            last  = float(series.iloc[-1])
            prev  = float(series.iloc[-2])
            high  = float(series.max())

            if last >= high * 0.995:                    # 52주 고가의 99.5% 이상
                results.append({
                    "ticker": ticker,
                    "name":   ticker,
                    "price":  round(last, 2),
                    "change": round((last - prev) / prev * 100, 2),
                    "high":   round(high, 2),
                    "market": "US",
                })
        except Exception:
            continue

    log.info(f"미국 신고가 종목 {len(results)}개 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 2. 한국 — KOSPI / KOSDAQ 신고가 종목
# ─────────────────────────────────────────────

def get_korea_ath_stocks(top_n: int = 200) -> list[dict]:
    """KOSPI·KOSDAQ 시총 상위 종목 중 52주 신고가 달성 종목 반환"""
    start = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")
    end   = datetime.now().strftime("%Y-%m-%d")

    results = []
    for market in ["KOSPI", "KOSDAQ"]:
        listing = fdr.StockListing(market)

        # 시가총액 기준 상위 top_n 종목만 조회 (속도 최적화)
        if "Marcap" in listing.columns:
            listing = listing.nlargest(top_n, "Marcap")
        else:
            listing = listing.head(top_n)

        log.info(f"{market} {len(listing)}종목 조회 시작")

        for _, row in listing.iterrows():
            code = str(row.get("Code", row.get("Symbol", "")))
            name = str(row.get("Name", code))
            try:
                df = fdr.DataReader(code, start, end)
                if df.empty or len(df) < 10:
                    continue

                last  = float(df["Close"].iloc[-1])
                prev  = float(df["Close"].iloc[-2])
                high  = float(df["High"].max())

                if last >= high * 0.995:
                    results.append({
                        "ticker": code,
                        "name":   name,
                        "price":  int(last),
                        "change": round((last - prev) / prev * 100, 2),
                        "high":   int(high),
                        "market": market,
                    })
            except Exception:
                continue

    log.info(f"한국 신고가 종목 {len(results)}개 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 3. 이메일 포맷
# ─────────────────────────────────────────────

def _table_html(stocks: list[dict], title: str, currency: str) -> str:
    if not stocks:
        return (
            f"<h2 style='color:#333'>{title}</h2>"
            f"<p style='color:#888'>오늘 해당 종목 없음</p>"
        )

    def price_fmt(p):
        return f"{p:,.2f}" if currency == "USD" else f"{p:,}"

    rows = ""
    for s in stocks:
        color = "#c0392b" if s["change"] > 0 else "#2980b9"
        sign  = "+" if s["change"] > 0 else ""
        rows += (
            f"<tr>"
            f"<td style='padding:8px'>{s['ticker']}</td>"
            f"<td style='padding:8px'>{s['name']}</td>"
            f"<td style='padding:8px;text-align:right'>{price_fmt(s['price'])} {currency}</td>"
            f"<td style='padding:8px;text-align:right;color:{color};font-weight:bold'>"
            f"{sign}{s['change']}%</td>"
            f"</tr>"
        )

    return f"""
    <h2 style='color:#1a1a2e;margin-top:30px'>{title} — {len(stocks)}종목</h2>
    <table style='border-collapse:collapse;width:100%;font-size:14px'>
      <thead>
        <tr style='background:#1a1a2e;color:#fff'>
          <th style='padding:10px;text-align:left'>티커</th>
          <th style='padding:10px;text-align:left'>종목명</th>
          <th style='padding:10px;text-align:right'>현재가</th>
          <th style='padding:10px;text-align:right'>등락률</th>
        </tr>
      </thead>
      <tbody>{''.join(f'<tr style="background:{"#f9f9f9" if i%2==0 else "#fff"}">' + row.split('</tr>')[0].split('<tr>')[1] + '</tr>' for i, row in enumerate(rows.split('<tr>')[1:]))}</tbody>
    </table>"""


def build_html_email(us: list[dict], kr: list[dict]) -> str:
    today_str = datetime.now().strftime("%Y년 %m월 %d일 (%a)")

    us_table = _table_html(us, "🇺🇸 미국 S&P 500", "USD")
    kr_table = _table_html(kr, "🇰🇷 한국 KOSPI / KOSDAQ", "KRW")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:720px;margin:auto;padding:20px;background:#fafafa">

  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 신고가(ATH) 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:14px">{today_str} 기준 | 52주 신고가(±0.5%) 달성 종목</p>
  </div>

  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    <div style="display:flex;gap:20px;flex-wrap:wrap">
      <div style="background:#eaf4ff;border-radius:6px;padding:12px 20px">
        <div style="font-size:12px;color:#555">미국 신고가</div>
        <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
      </div>
      <div style="background:#eaffea;border-radius:6px;padding:12px 20px">
        <div style="font-size:12px;color:#555">한국 신고가</div>
        <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
      </div>
    </div>
  </div>

  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    {us_table}
    <div style="margin-top:32px"></div>
    {kr_table}
  </div>

  <p style="font-size:11px;color:#aaa;margin-top:20px;text-align:center">
    본 메일은 자동 발송됩니다. 52주 신고가 기준이며 투자 권유가 아닙니다.<br>
    Powered by GitHub Actions + yfinance + FinanceDataReader
  </p>
</body>
</html>"""


# ─────────────────────────────────────────────
# 4. 이메일 발송
# ─────────────────────────────────────────────

def send_email(html: str) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pwd  = os.environ["GMAIL_APP_PASSWORD"]
    recipient  = os.environ.get("RECIPIENT_EMAIL", "ykhan@dacpole.com")

    today_str = datetime.now().strftime("%Y-%m-%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 ATH 리포트 {today_str} — {len(html)} chars"
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html"))

    # 제목 다시 세팅 (len 제거)
    us_count = html.count("🇺🇸")
    msg.replace_header("Subject", f"📈 ATH 리포트 {today_str}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pwd)
        server.sendmail(gmail_user, recipient, msg.as_string())

    log.info(f"✅ 이메일 발송 완료 → {recipient}")


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    log.info("=== 일일 ATH 리포트 시작 ===")

    log.info("📊 미국 신고가 조회 중...")
    us_stocks = get_us_ath_stocks()

    log.info("📊 한국 신고가 조회 중...")
    kr_stocks = get_korea_ath_stocks(top_n=200)

    log.info("📧 이메일 생성 및 발송 중...")
    html = build_html_email(us_stocks, kr_stocks)
    send_email(html)

    log.info(f"=== 완료: 미국 {len(us_stocks)}종목 / 한국 {len(kr_stocks)}종목 ===")


if __name__ == "__main__":
    main()
