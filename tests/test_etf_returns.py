"""Regression tests for ETF CAGR, lifetime returns, ranking, and email columns."""
import re
import unittest
from datetime import date

from src.main import _calc_perf, build_etf_info, etf_section_html


class EtfReturnTests(unittest.TestCase):
    def test_compound_returns_for_all_four_periods(self):
        dates = [date(2016, 10, 7), date(2021, 10, 7), date(2023, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        closes = [100, 161.051, 194.87171, 235.7947691, 259.37424601]
        self.assertEqual(_calc_perf(dates, closes),
                         (10.0, 10.0, 10.0, 10.0, 159.4, dates[0]))

    def test_exact_one_year_history_is_eligible(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (20.0, None, None, None, 20.0, dates[0]))

    def test_exact_three_year_history_without_longer_periods(self):
        dates = [date(2023, 10, 7), date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 121, 133.1]),
                         (10.0, 10.0, None, None, 33.1, dates[0]))

    def test_exact_five_year_history_without_ten_year_history(self):
        dates = [date(2021, 10, 7), date(2023, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 121, 146.41, 161.051]),
                         (10.0, 10.0, 10.0, None, 61.1, dates[0]))

    def test_history_under_one_year_still_has_cumulative_return(self):
        dates = [date(2026, 1, 1), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (None, None, None, None, 20.0, dates[0]))

    def test_weekend_anniversary_uses_previous_trading_close(self):
        dates = [date(2025, 10, 3), date(2025, 10, 6), date(2026, 10, 5)]
        result = _calc_perf(dates, [100, 110, 121])
        self.assertEqual(result[0], 21.0)
        self.assertEqual(result[4], 21.0)

    def test_leap_day_anniversary_uses_february_28(self):
        dates = [date(2023, 2, 28), date(2024, 2, 29)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (20.0, None, None, None, 20.0, dates[0]))

    def test_three_year_leap_day_anniversary(self):
        dates = [date(2021, 2, 28), date(2023, 2, 28), date(2024, 2, 29)]
        self.assertEqual(_calc_perf(dates, [100, 121, 133.1]),
                         (10.0, 10.0, None, None, 33.1, dates[0]))

    def test_invalid_or_missing_histories(self):
        for dates, closes in [([], []), ([date(2026, 1, 1)], [100]),
                              ([date(2025, 1, 1)], [100, 110])]:
            with self.subTest(dates=dates, closes=closes):
                self.assertEqual(_calc_perf(dates, closes),
                                 (None, None, None, None, None, None))

    def test_invalid_prices_do_not_produce_returns(self):
        dates = [date(2016, 10, 7), date(2026, 10, 7)]
        for closes in [[0, 100], [-100, 100], [100, 0],
                       [100, float("nan")], [float("inf"), 100]]:
            with self.subTest(closes=closes):
                self.assertEqual(_calc_perf(dates, closes)[:5],
                                 (None, None, None, None, None))

    def test_invalid_first_price_does_not_remove_valid_recent_returns(self):
        dates = [date(2016, 10, 7), date(2021, 10, 7), date(2023, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        closes = [0, 100, 121, 146.41, 161.051]
        self.assertEqual(_calc_perf(dates, closes),
                         (10.0, 10.0, 10.0, None, None, dates[0]))

    def test_zero_and_negative_returns_are_valid(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 100]),
                         (0.0, None, None, None, 0.0, dates[0]))
        self.assertEqual(_calc_perf(dates, [100, 90]),
                         (-10.0, None, None, None, -10.0, dates[0]))

    def test_cumulative_return_is_not_annualized(self):
        dates = [date(2016, 10, 7), date(2025, 10, 7), date(2026, 10, 7)]
        result = _calc_perf(dates, [100, 200, 200])
        self.assertEqual(result[3], 7.2)
        self.assertEqual(result[4], 100.0)


class EtfRankingAndHtmlTests(unittest.TestCase):
    def test_one_year_descending_ranking_ignores_other_returns(self):
        us = [
            {"ticker": "US_LOW", "asset_type": "ETF", "cagr1y": -5.0,
             "cagr3y": 999, "cagr5y": 80, "cumulative_return": 9999},
            {"ticker": "US_HIGH", "asset_type": "ETF", "cagr1y": 40.0,
             "cagr3y": 1, "cagr5y": 1, "cumulative_return": 10},
            {"ticker": "STOCK", "asset_type": "주식", "cagr1y": 999},
        ]
        kr = [
            {"ticker": "KR_MID", "asset_type": "ETF", "cagr1y": 15.0,
             "cagr3y": None, "cagr10y": 90, "cumulative_return": None},
            {"ticker": "KR_ZERO", "asset_type": "ETF", "cagr1y": 0.0},
            {"ticker": "KR_NEW", "asset_type": "ETF", "cagr1y": None,
             "cumulative_return": 500},
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

    def test_cards_show_all_five_return_metrics_in_order(self):
        row = {"ticker": "ETF", "name": "Example ETF", "market": "US",
               "cagr1y": 12.3, "cagr3y": 9.1, "cagr5y": 8.0, "cagr10y": 6.0,
               "cumulative_return": 159.4}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        periods = re.findall(r'data-period="([^"]+)"', html)
        self.assertEqual(periods, ["1y", "3y", "5y", "10y", "cumulative"])
        for expected in ["+12.3%", "+9.1%", "+8.0%", "+6.0%", "+159.4%"]:
            self.assertIn(expected, html)
        self.assertIn("1년 연평균수익률 내림차순", html)

    def test_missing_long_period_returns_keep_valid_cumulative_return(self):
        row = {"ticker": "NEW", "name": "New ETF", "cagr1y": 20.0,
               "cumulative_return": 30.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn("+20.0%", html)
        self.assertIn("+30.0%", html)
        self.assertEqual(html.count('<span class="flat">-</span>'), 3)

    def test_missing_cumulative_return_is_shown_as_dash(self):
        row = {"ticker": "ETF", "name": "Example ETF", "cagr1y": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn('data-period="cumulative"', html)
        self.assertEqual(html.count('<span class="flat">-</span>'), 4)

    def test_footer_explains_cumulative_return_basis(self):
        row = {"ticker": "ETF", "name": "Example ETF", "cagr1y": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn("최초 거래일 종가 대비 최신 종가", html)
        self.assertIn("연환산하지 않음", html)
        self.assertIn("분배금 미반영 가격수익률", html)

    def test_empty_pool_renders_without_errors(self):
        info = build_etf_info([], [])
        self.assertEqual(info, {"rows": [], "pool": 0, "with_ret": 0})
        self.assertIn("해당 ETF 없음", etf_section_html(info))


if __name__ == "__main__":
    unittest.main()
