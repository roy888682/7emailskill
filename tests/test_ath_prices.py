"""ATH quotes stay on one dated scale and membership follows the final quote."""
import copy
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from src.main import (_ath_price_metrics, _current_ath_rows, _etf_price_performance,
                      _history_prices, _split_factor_after, _us_reference_metadata,
                      _refresh_etf_market_history, compute_new_tickers,
                      get_us_ath, synchronize_etf_market_dates)


ANCHOR = date(2026, 11, 5)
BASIS = "Yahoo 제공 수정주가(auto_adjust)"


def candidate(ticker, latest, *, end="2026-11-05", peak=100.0, asset="ETF"):
    days = [date(2020, 1, 2), date(2026, 6, 22), date.fromisoformat(end)]
    prices = [50.0, peak, latest]
    item = {"ticker": ticker, "market": "US", "asset_type": asset,
            "url": "https://m.stock.naver.com/worldstock/etf/" + ticker + ".O"}
    if asset == "ETF":
        item.update(_etf_price_performance(days, prices, price_basis=BASIS, price_currency="USD"))
    item.update(_ath_price_metrics(days, prices, price_basis=BASIS))
    return item


class AthPriceTests(unittest.TestCase):
    def test_actual_soxx_closes_reproduce_the_gap_and_trim_future_quotes(self):
        values = _ath_price_metrics(
            [date(2001, 7, 13), date(2026, 6, 22), date(2026, 11, 4), ANCHOR, date(2026, 11, 6)],
            [4.45121622086, 218.19401550293, 150.13666788737, 131.89999389648438, 999.0],
            price_basis=BASIS, anchor=ANCHOR)
        self.assertEqual(values["price"], 131.89999389648438)
        self.assertEqual(values["ath_price"], 218.19401550293)
        self.assertEqual(values["ath_date"], "2026-06-22")
        self.assertEqual(values["ath_end_date"], "2026-11-05")
        self.assertEqual(values["gap"], -39.55)

    def test_complete_pool_rebuild_can_add_remove_and_exclude_a_stale_ath(self):
        stock = candidate("STOCK", 95, asset="주식")
        soxx = candidate("SOXX", 131.89999389648438, peak=218.19401550293)
        entered = candidate("ENTERED", 95)
        stale = candidate("STALE", 99, end="2026-11-04")
        pool = [soxx, entered, stale]
        before = copy.deepcopy(pool)
        rows = _current_ath_rows([stock, soxx, stale], pool, "US", ANCHOR)
        self.assertEqual({row["ticker"] for row in rows}, {"STOCK", "ENTERED"})
        self.assertEqual(pool, before)
        snapshots = {"US": {"2026-11-04": ["STOCK"]}}
        self.assertEqual([row["ticker"] for row in compute_new_tickers(rows, snapshots, "US", "2026-11-05")], ["ENTERED"])

    def test_mixed_adjusted_endpoint_is_not_published_as_a_threefold_gain(self):
        index = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"])
        for raw, adjusted in (([300, 450, 450], [100, 150, 450]),
                              ([100, 150, 150], [100, 150, 450])):
            frame = pd.DataFrame({"Close": raw, "Adj Close": adjusted}, index=index)
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, "adjusted|Adjusted"):
                _history_prices(frame)
        with self.assertRaisesRegex(RuntimeError, "missing"):
            _history_prices(pd.DataFrame({"Close": [100, 101]}, index=index[:2]))

    def test_declared_cash_distribution_can_change_adjustment_ratio(self):
        frame = pd.DataFrame({"Close": [100.0, 70.0], "Adj Close": [70.0, 70.0],
                              "Dividends": [0.0, 30.0]}, index=pd.to_datetime(["2026-11-04", "2026-11-05"]))
        self.assertEqual(_history_prices(frame)[1], [70.0, 70.0])

    def test_reference_accepts_provider_history_before_or_after_split_cache_revision(self):
        item = {"ticker": "SOXX", "url": "https://m.stock.naver.com/worldstock/etf/SOXX.O"}
        for quoted, factor in ((450.41, 3.0), (150.1365, 1.0)):
            reference = {"price": quoted, "date": "2026-11-04", "source_url": "https://api.stock.naver.com/chart"}
            with patch("src.main.us_naver_links.verified_close", return_value=reference, create=True):
                checked = _us_reference_metadata(item, 150.13666788737, date(2026, 11, 4),
                                                 adjusted_price=150.13666788737, split_factor=3)
            self.assertEqual(checked["price_reference_status"], "matched")
            self.assertEqual(checked["reference_split_factor"], factor)
            self.assertAlmostEqual(checked["reference_price"], 150.1366, places=3)

    def test_full_history_applies_recent_actions_before_historical_anchor_trim(self):
        index = pd.to_datetime(["2001-07-13", "2026-06-22", "2026-11-04", "2026-11-05"])
        closes = [4.45121622086, 218.19401550293, 150.13666788737, 131.89999389648438]
        frame = pd.DataFrame({"Close": closes, "Adj Close": closes, "Stock Splits": [0, 0, 0, 3]}, index=index)
        item = {"ticker": "SOXX", "market": "US", "asset_type": "ETF",
                "url": "https://m.stock.naver.com/worldstock/etf/SOXX.O"}
        reference = {"price": 450.41, "date": "2026-11-04", "source_url": "https://api.stock.naver.com/chart"}
        with patch("src.main.yf.Ticker") as ticker, patch("src.main.us_naver_links.verified_close", return_value=reference, create=True):
            ticker.return_value.history.return_value = frame
            result = _refresh_etf_market_history(item, "US", date(2026, 11, 4))
            ticker.return_value.history.assert_called_once_with(period="max", auto_adjust=False, actions=True, timeout=12)
        self.assertEqual(result["price_end_date"], "2026-11-04")
        self.assertAlmostEqual(result["latest_adjusted_price"], closes[2])
        self.assertEqual(result["reference_split_factor"], 3)
        self.assertEqual(_split_factor_after([(date(2024, 3, 7), 3), (ANCHOR, 3)], date(2026, 11, 4)), 3)

    def test_inconsistent_unrecoverable_candidate_remains_unavailable_in_pool(self):
        item = candidate("SOXX", 450.41, peak=464.84)
        item["price_reference_status"] = "mismatch"
        pool = [item]
        info = {"us_last": ANCHOR, "kr_last": ANCHOR}
        with patch("src.main._refresh_etf_market_history", side_effect=RuntimeError("rate limited")):
            proof = synchronize_etf_market_dates([item], [], info, attempts=1, comparison_etfs=pool)
        self.assertIs(pool[0], item)
        self.assertEqual(item["date_status"], "unavailable")
        self.assertIsNone(item["latest_adjusted_price"])
        self.assertEqual(proof["status_counts"]["unavailable"], 1)
        self.assertEqual(_current_ath_rows([item], pool, "US", ANCHOR), [])

    def test_us_collector_uses_anchor_before_ath_selection(self):
        days = pd.to_datetime(["2020-01-02", "2026-06-22", "2026-11-05", "2026-11-06"])
        data = {"SOXX": pd.Series([50.0, 218.19401550293, 131.89999389648438, 999.0], index=days),
                "ENTERED": pd.Series([50.0, 100.0, 95.0, 999.0], index=days),
                "STOCK": pd.Series([50.0, 100.0, 96.0, 999.0], index=days)}
        flags = {"SOXX": True, "ENTERED": True, "STOCK": False}
        with patch("src.main.get_us_tickers", return_value=(list(data), {}, set(), {}, flags)), \
                patch("src.main.dl", return_value=data), patch("src.main.get_us_industry", return_value=None), \
                patch("src.main.enrich_us_etf", return_value={}), patch("src.main.yf.Ticker"), \
                patch("src.main.us_naver_links.resolve_us_links"):
            pool = []
            rows = get_us_ath(1300, pool, us_last=ANCHOR)
        self.assertEqual({row["ticker"] for row in rows}, {"ENTERED", "STOCK"})
        self.assertEqual({row["ticker"] for row in pool}, {"ENTERED", "SOXX"})
        self.assertTrue(all(row["ath_end_date"] == "2026-11-05" for row in rows + pool))


if __name__ == "__main__":
    unittest.main()
