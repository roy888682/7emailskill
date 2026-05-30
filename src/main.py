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
from pykrx import stock as krx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. 미국 — S&P 500 신고가 종목
# ─────────────────────────────────────────────

def get_sp500_tickers():
    df = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


def get_us_ath_stocks():
    tickers = get_sp500_tickers()
    start = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")
    log.info(f"미국 {len(tickers)}종목 다운로드 중...")

    raw = yf.download(tickers, start=start, progress=False, auto_adjust=True, group_by="ticker")

    results = []
    for ticker in tickers:
        try:
            try:
                series = raw[ticker]["Close"].dropna()
            except KeyError:
                series = raw["Close"].dropna()

            if len(series) < 10:
                continue

            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            high = float(series.max())

            if last >= high * 0.995:
                results.append({
                    "ticker": ticker,
                    "name":   ticker,
                    "price":  round(last, 2),
                    "change": round((last - prev) / prev * 100, 2),
                    "market": "US",
                })
        except Exception:
            continue

    log.info(f"미국 신고가 {len(results)}종목 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 2. 한국 — KOSPI / KOSDAQ 신고가 종목
# ─────────────────────────────────────────────

def get_korea_ath_stocks(top_n=150):
    today = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=380)).strftime("%Y%m%d")

    results = []
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            tickers = krx.get_market_ticker_list(today, market=market)[:top_n]
        except Exception as e:
            log.error(f"{market} 티커 조회 실패: {e}")
            continue

        log.info(f"{market} {len(tickers)}종목 조회 중...")
        for ticker in tickers:
            try:
                df = krx.get_market_ohlcv_by_date(start, today, ticker)
                if df.empty or len(df) < 10:
                    continue

                last = float(df["종가"].iloc[-1])
                prev = float(df["종가"].iloc[-2])
                high = float(df["고가"].max())

                if last >= high * 0.995:
                    name = krx.get_market_ticker_name(ticker)
                    results.append({
                        "ticker": ticker,
                        "name":   name,
                        "price":  int(last),
                        "change": round((last - prev) / prev * 100, 2),
                        "market": market,
                    })
            except Exception:
                continue

    log.info(f"한국 신고가 {len(results)}종목 발견")
    return sorted(results, key=lambda x: -x["change"])


# ─────────────────────────────────────────────
# 3. 이메일 HTML 포맷
# ─────────────────────────────────────────────

def _table_html(stocks, title, currency):
    if not stocks:
        return f"<h2 style='color:#333'>{title}</h2><p style='color:#888'>오늘 해당 종목 없음</p>"

    def fmt(p):
        return f"{p:,.2f}" if currency == "USD" else f"{p:,}"

    rows = ""
    for i, s in enumerate(stocks):
        bg    = "#f9f9f9" if i % 2 == 0 else "#ffffff"
        color = "#c0392b" if s["change"] > 0 else "#2980b9"
        sign  = "+" if s["change"] > 0 else ""
        rows += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:8px'>{s['ticker']}</td>"
            f"<td style='padding:8px'>{s['name']}</td>"
            f"<td style='padding:8px;text-align:right'>{fmt(s['price'])} {currency}</td>"
            f"<td style='padding:8px;text-align:right;color:{color};font-weight:bold'>{sign}{s['change']}%</td>"
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
      <tbody>{rows}</tbody>
    </table>"""


def build_html_email(us, kr):
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:720px;margin:auto;padding:20px;background:#fafafa">
  <div style="background:#1a1a2e;color:#fff;padding:24px;border-radius:8px">
    <h1 style="margin:0;font-size:22px">📈 일일 신고가(ATH) 리포트</h1>
    <p style="margin:6px 0 0;opacity:0.7;font-size:14px">{today_str} | 52주 신고가(±0.5%) 달성 종목</p>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    <span style="background:#eaf4ff;border-radius:6px;padding:10px 20px;margin-right:12px;display:inline-block">
      <div style="font-size:12px;color:#555">미국 신고가</div>
      <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(us)}종목</div>
    </span>
    <span style="background:#eaffea;border-radius:6px;padding:10px 20px;display:inline-block">
      <div style="font-size:12px;color:#555">한국 신고가</div>
      <div style="font-size:24px;font-weight:bold;color:#1a1a2e">{len(kr)}종목</div>
    </span>
  </div>
  <div style="background:#fff;padding:20px;border-radius:8px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
    {_table_html(us, "🇺🇸 미국 S&P 500", "USD")}
    <div style="margin-top:32px"></div>
    {_table_html(kr, "🇰🇷 한국 KOSPI / KOSDAQ", "KRW")}
  </div>
  <p style="font-size:11px;color:#aaa;margin-top:20px;text-align:center">
    자동 발송 | 52주 신고가 기준 | 투자 권유 아님
  </p>
</body></html>"""


# ─────────────────────────────────────────────
# 4. 이메일 발송
# ─────────────────────────────────────────────

def send_email(html):
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
    us = get_us_ath_stocks()
    kr = get_korea_ath_stocks(top_n=150)
    html = build_html_email(us, kr)
    send_email(html)
    log.info(f"=== 완료: 미국 {len(us)}종목 / 한국 {len(kr)}종목 ===")

if __name__ == "__main__":
    main()
