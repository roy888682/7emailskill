"""Reproduce the TQQQ figure for the sent report, without SMTP or credentials."""
import bisect
import json
import math
from datetime import date
from pathlib import Path
import sys
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.main import _calc_perf
REFERENCE = date(2026, 10, 8)
history = yf.Ticker("TQQQ").history(period="max", auto_adjust=False, actions=True)
if history.empty:
    raise RuntimeError("Yahoo returned no history")
history = history.loc[[ts.date() <= REFERENCE for ts in history.index]].copy()
history = history.dropna(subset=["Close", "Adj Close"])
dates = [ts.date() for ts in history.index]
last = dates[-1]
if last != REFERENCE:
    raise RuntimeError(f"Expected {REFERENCE}, found {last}")
target = last.replace(year=last.year - 10)
idx = bisect.bisect_right(dates, target) - 1
start = dates[idx]
adj = [float(v) for v in history["Adj Close"]]
close = [float(v) for v in history["Close"]]
ratio = adj[-1] / adj[idx]
unrounded = (ratio ** .1 - 1) * 100
rounded = _calc_perf(dates, adj)[3]
actual_days = (last - start).days
result = {
    "ticker": "TQQQ", "provider": "Yahoo Finance via yfinance", "yfinance_version": yf.__version__,
    "reference_date": str(REFERENCE), "target_date": str(target), "start_date": str(start),
    "end_date": str(last), "calendar_days": actual_days,
    "start_close_split_adjusted_usd": close[idx], "start_adjusted_close_usd": adj[idx],
    "end_close_split_adjusted_usd": close[-1], "end_adjusted_close_usd": adj[-1],
    "adjusted_price_ratio": ratio, "cumulative_10y_return_pct": (ratio - 1) * 100,
    "cagr_10y_unrounded_pct": unrounded, "repo_cagr_10y_pct": rounded,
    "matches_41_3": rounded == 41.3,
    "cagr_using_actual_days_365_2425_pct": (ratio ** (365.2425 / actual_days) - 1) * 100,
    "price_only_cagr_pct": ((close[-1] / close[idx]) ** .1 - 1) * 100,
    "all_repo_returns_pct": list(_calc_perf(dates, adj)[:5]),
    "splits": [{"date": str(ts.date()), "ratio": float(row["Stock Splits"])}
               for ts,row in history.iterrows() if float(row.get("Stock Splits",0)) != 0],
    "recent_distributions": [{"date": str(ts.date()), "dividend": float(row["Dividends"])}
                             for ts,row in history.iterrows()
                             if ts.date() >= date(2026,1,1) and float(row.get("Dividends",0)) != 0],
}
# Verify Yahoo's adjusted Close equals the code's auto_adjust=True Close.
adjusted = yf.Ticker("TQQQ").history(period="max", auto_adjust=True, actions=False)
adjusted = adjusted.loc[[ts.date() <= REFERENCE for ts in adjusted.index]]
for d, expected in ((start, adj[idx]), (last, adj[-1])):
    matching = adjusted.loc[[ts.date() == d for ts in adjusted.index], "Close"]
    if len(matching) != 1:
        raise RuntimeError("Missing auto-adjust verification endpoint")
    observed = float(matching.iloc[0])
    if not math.isclose(observed, expected, rel_tol=1e-6):
        raise RuntimeError(f"Adjusted prices differ on {d}: {observed} vs {expected}")
result["auto_adjust_endpoints_match"] = True
# Independently recover the same dates/prices via the Yahoo chart JSON source.
from curl_cffi import requests
first_stamp = int(history.index[0].timestamp()) - 86400
last_stamp = int(history.index[-1].timestamp()) + 86400
chart_response = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/TQQQ",
    params={"period1": first_stamp, "period2": last_stamp, "interval": "1d",
            "events": "div,splits", "includeAdjustedClose": "true"},
    impersonate="chrome", timeout=45)
chart_response.raise_for_status()
chart = chart_response.json()["chart"]["result"][0]
from datetime import datetime
from zoneinfo import ZoneInfo
chart_rows = []
for i, stamp in enumerate(chart["timestamp"]):
    day = datetime.fromtimestamp(stamp, ZoneInfo("America/New_York")).date()
    if day in (start, last):
        chart_rows.append({"date": str(day),
            "close": chart["indicators"]["quote"][0]["close"][i],
            "adjusted_close": chart["indicators"]["adjclose"][0]["adjclose"][i]})
result["raw_chart_endpoints"] = chart_rows
if len(chart_rows) != 2:
    raise RuntimeError("Raw chart endpoints unavailable")
for row, expected in zip(chart_rows, (adj[idx], adj[-1])):
    if not math.isclose(row["adjusted_close"], expected, rel_tol=1e-6):
        raise RuntimeError("Raw chart adjusted prices do not match")
output = Path("work/tqqq-verification")
output.mkdir(parents=True, exist_ok=True)
(output / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
history.to_csv(output / "yahoo-history-through-2026-10-08.csv")
print("TQQQ_VERIFICATION_RESULT:" + json.dumps(result, ensure_ascii=False), flush=True)
if not result["matches_41_3"]:
    raise RuntimeError("Recomputed value does not match email 41.3%")
