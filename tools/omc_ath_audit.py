import json
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
import yfinance as yf
from src.main import _history_prices, _ath_price_metrics

anchor = date(2026, 11, 18)
raw = yf.download(["OMC"], period="max", progress=False, auto_adjust=False, actions=True, group_by="ticker")
frame = raw["OMC"] if isinstance(raw.columns, pd.MultiIndex) else raw
frame = frame.loc[frame.index.date <= anchor]
assert len(frame) > 1000
def observations(column, count=3):
    values = frame[column].dropna().nlargest(count)
    return [{"date": stamp.date().isoformat(), "value": float(value),
             "close": float(frame.loc[stamp, "Close"]),
             "adjusted_close": float(frame.loc[stamp, "Adj Close"]),
             "high": float(frame.loc[stamp, "High"])}
            for stamp, value in values.items()]
dates, adjusted, closes = _history_prices(frame, anchor=anchor)
metrics = _ath_price_metrics(dates, adjusted, price_basis="Yahoo dividend/split-adjusted Close", anchor=anchor)
result = {
    "ticker": "OMC", "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    "report_market_date": anchor.isoformat(), "provider": "Yahoo Finance via yfinance",
    "first_date": dates[0].isoformat(), "last_date": dates[-1].isoformat(),
    "observations": len(dates), "program_metrics": metrics,
    "highest_unadjusted_closes": observations("Close"),
    "highest_adjusted_closes": observations("Adj Close"),
    "highest_intraday_highs": observations("High"),
    "latest": {column: float(frame.iloc[-1][column]) for column in ["Close","Adj Close","High"]},
    "recent_dividends": [{"date": stamp.date().isoformat(),"dividend":float(value)}
                        for stamp,value in frame.loc[frame["Dividends"] > 0,"Dividends"].tail(8).items()],
    "splits": [{"date":stamp.date().isoformat(),"ratio":float(value)}
               for stamp,value in frame.loc[frame["Stock Splits"] > 0,"Stock Splits"].items()]
}
print("OMC_ATH_AUDIT:" + json.dumps(result, ensure_ascii=False, default=str))
Path("work").mkdir(exist_ok=True)
Path("work/omc-ath-audit.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
