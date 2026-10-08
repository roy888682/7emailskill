"""Regression tests for ETF CAGR periods, ranking, and email columns."""
import re
import unittest
from datetime import date

from src.main import _calc_perf, build_etf_info, etf_section_html


class EtfReturnTests(unittest.TestCase):
    def test_compound_returns_for_all_three_periods(self):
        dates = [date(2016, 10, 7), date(2021, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        closes = [100, 161.051, 235.7947691, 259.37424601]
        self.assertEqual(_calc_perf(dates, closes),
                         (10.0, 10.0, 10.0, dates[0]))

    def test_exact_one_year_history_is_eligible(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (20.0, None, None, dates[0]))

    def test_exact_five_year_history_without_ten_year_history(self):
        dates = [date(2021, 10, 7), date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 146.41, 161.051]),
                         (10.0, 10.0, None, dates[0]))

    def test_history_under_one_year_has_no_return(self):
        dates = [date(2026, 1, 1), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (None, None, None, dates[0]))

    def test_weekend_anniversary_uses_previous_trading_close(self):
        dates = [date(2025, 10, 3), date(2025, 10, 6), date(2026, 10, 5)]
        self.assertEqual(_calc_perf(dates, [100, 110, 121])[0], 21.0)

    def test_leap_day_anniversary_uses_february_28(self):
        dates = [date(2023, 2, 28), date(2024, 2, 29)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (20.0, None, None, dates[0]))

    def test_invalid_or_missing_histories(self):
        for dates, closes in [([], []), ([date(2026, 1, 1)], [100]),
                              ([date(2025, 1, 1)], [100, 110])]:
            with self.subTest(dates=dates, closes=closes):
                self.assertEqual(_calc_perf(dates, closes),
                                 (None, None, None, None))

    def test_invalid_prices_do_not_produce_returns(self):
        dates = [date(2016, 10, 7), date(2026, 10, 7)]
        for closes in [[0, 100], [-100, 100], [100, 0],
                       [100, float("nan")], [float("inf"), 100]]:
            with self.subTest(closes=closes):
                self.assertEqual(_calc_perf(dates, closes)[:3],
                                 (None, None, None))

    def test_zero_and_negative_returns_are_valid(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 100])[0], 0.0)
        self.assertEqual(_calc_perf(dates, [100, 90])[0], -10.0)


class EtfRankingAndHtmlTests(unittest.TestCase):
    def test_one_year_descending_ranking_across_markets(self):
        us = [
            {"ticker": "US_LOW", "asset_type": "ETF", "cagr1y": -5.0, "cagr5y": 80},
            {"ticker": "US_HIGH", "asset_type": "ETF", "cagr1y": 40.0, "cagr5y": 1},
            {"ticker": "STOCK", "asset_type": "주식", "cagr1y": 999},
        ]
        kr = [
            {"ticker": "KR_MID", "asset_type": "ETF", "cagr1y": 15.0, "cagr10y": 90},
            {"ticker": "KR_ZERO", "asset_type": "ETF", "cagr1y": 0.0},
            {"ticker": "KR_NEW", "asset_type": "ETF", "cagr1y": None},
        ]
        info = build_etf_info(us, kr)
        self.assertEqual([s["ticker"] for s in info["rows"]],
                         ["US_HIGH", "KR_MID", "KR_ZERO", "US_LOW"])
        self.assertEqual(info["pool"], 5)
        self.assertEqual(info["with_ret"], 4)

    def test_existing_top_twenty_limit(self):
        etfs = [{"ticker": str(i), "asset_type": "ETF", "cagr1y": float(i)}
                for i in range(25)]
        info = build_etf_info(etfs, [])
        self.assertEqual(len(info["rows"]), 20)
        self.assertEqual([s["cagr1y"] for s in info["rows"]],
                         list(map(float, range(24, 4, -1))))
        self.assertEqual((info["pool"], info["with_ret"]), (25, 25))

    def test_html_headers_and_values_are_in_one_five_ten_year_order(self):
        row = {"ticker": "ETF", "name": "Example ETF", "market": "US",
               "cagr1y": 12.3, "cagr5y": 8.0, "cagr10y": 6.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        headers = re.findall(r"<th\b[^>]*>(.*?)</th>", html, re.S)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", html, re.S)
        self.assertEqual(len(headers), 11)
        self.assertEqual(len(cells), 11)
        self.assertEqual(headers[5:8], ["최근 1년 연평균수익률 ↓",
                                      "최근 5년 연평균수익률",
                                      "최근 10년 연평균수익률"])
        for cell, expected in zip(cells[5:8], ["+12.3%", "+8.0%", "+6.0%"]):
            self.assertIn(expected, cell)
        self.assertIn("1년 수익률 내림차순", html)

    def test_missing_long_period_returns_are_shown_as_dashes(self):
        row = {"ticker": "NEW", "name": "New ETF", "cagr1y": 20.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", html, re.S)
        self.assertIn("+20.0%", cells[5])
        self.assertIn(">-</span>", cells[6])
        self.assertIn(">-</span>", cells[7])

    def test_empty_pool_renders_without_errors(self):
        info = build_etf_info([], [])
        self.assertEqual(info, {"rows": [], "pool": 0, "with_ret": 0})
        self.assertIn("해당 ETF 없음", etf_section_html(info))


if __name__ == "__main__":
    unittest.main()
