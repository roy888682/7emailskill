"""Exercise the actual US download/parser path rather than replacing dl itself."""
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from src.main import dl, get_us_ath


def history(start=100.0, rows=12):
    prices = [start + offset for offset in range(rows)]
    return pd.DataFrame({
        "Close": prices,
        "Adj Close": prices,
        "Dividends": [0.0] * rows,
        "Stock Splits": [0.0] * (rows - 1) + [2.0],
    }, index=pd.date_range("2026-11-02", periods=rows, freq="B"))


class UsBatchPriceTests(unittest.TestCase):
    def test_actual_dl_parses_multiple_tickers_and_preserves_price_metadata(self):
        raw = pd.concat({"SPY": history(), "SOXX": history(200.0)}, axis=1)
        with patch("src.main.yf.download", return_value=raw) as download:
            result = dl(["SPY", "SOXX"], "1y", sleep=0)

        self.assertEqual(set(result), {"SPY", "SOXX"})
        self.assertEqual(result["SPY"].iloc[-1], 111.0)
        self.assertEqual(result["SOXX"].iloc[-1], 211.0)
        self.assertEqual(result["SPY"].attrs["raw_close_by_date"][date(2026, 11, 17)], 111.0)
        self.assertEqual(result["SPY"].attrs["split_events"], [(date(2026, 11, 17), 2.0)])
        download.assert_called_once_with(["SPY", "SOXX"], period="1y", progress=False,
                                         auto_adjust=False, actions=True, group_by="ticker")

    def test_single_ticker_supports_both_yahoo_column_shapes(self):
        frame = history()
        for raw in (frame, pd.concat({"SPY": frame}, axis=1)):
            with self.subTest(multi=isinstance(raw.columns, pd.MultiIndex)):
                with patch("src.main.yf.download", return_value=raw):
                    result = dl(["SPY"], "max", sleep=0)
                self.assertEqual(list(result), ["SPY"])
                self.assertEqual(result["SPY"].iloc[0], 100.0)

    def test_missing_ticker_is_logged_without_copying_another_tickers_prices(self):
        raw = pd.concat({"SPY": history()}, axis=1)
        with patch("src.main.yf.download", return_value=raw), self.assertLogs("src.main", level="WARNING") as logs:
            result = dl(["SPY", "SOXX"], "1y", sleep=0)
        self.assertEqual(list(result), ["SPY"])
        self.assertTrue(any("SOXX" in line and "KeyError" in line for line in logs.output))

    def test_total_batch_failure_is_logged_and_keeps_etf_refetch_available(self):
        for raw in (pd.DataFrame(), history()):
            with self.subTest(empty=raw.empty):
                with patch("src.main.yf.download", return_value=raw), self.assertLogs("src.main", level="ERROR") as logs:
                    self.assertEqual(dl(["SPY", "SOXX"], "1y", sleep=0), {})
                self.assertTrue(any("미국 가격 수집 실패" in line for line in logs.output))

    def test_valid_short_history_is_an_exclusion_not_a_collection_failure(self):
        with patch("src.main.yf.download", return_value=history(rows=3)):
            self.assertEqual(dl(["NEW"], "1y", sleep=0), {})

    def test_all_stock_collection_failures_cannot_be_published_as_zero_ath(self):
        universe = (["AAPL"], {"AAPL": "NASDAQ"}, {"AAPL"}, {"AAPL": "Apple"}, {})
        valid = pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-11-13", "2026-11-16"]))
        for responses, stage in (([{}], "1년"), ([{"AAPL": valid}, {}], "전체기간")):
            with self.subTest(stage=stage):
                with patch("src.main.get_us_tickers", return_value=universe), patch("src.main.dl", side_effect=responses):
                    with self.assertRaisesRegex(RuntimeError, "미국 일반주 " + stage + " 가격 수집 실패"):
                        get_us_ath(1400.0, comparison_etfs=[], us_last=date(2026, 11, 16))

    def test_valid_stock_prices_with_no_ath_candidates_are_allowed(self):
        universe = (["AAPL"], {"AAPL": "NASDAQ"}, {"AAPL"}, {"AAPL": "Apple"}, {})
        below_ath = pd.Series([100.0, 50.0], index=pd.to_datetime(["2026-11-13", "2026-11-16"]))
        with patch("src.main.get_us_tickers", return_value=universe), patch("src.main.dl", return_value={"AAPL": below_ath}) as download:
            self.assertEqual(get_us_ath(1400.0, comparison_etfs=[], us_last=date(2026, 11, 16)), [])
        download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
