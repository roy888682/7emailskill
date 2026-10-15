"""Regression tests for ETF CAGR, lifetime returns, ranking, and email columns."""
import re
import unittest
from datetime import date

from src.main import (_calc_perf, _etf_price_performance, _etf_lifetime_metrics,
                      build_etf_info, etf_section_html)


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
    @staticmethod
    def dated_etf(ticker, cumulative, **extra):
        return {"ticker": ticker, "asset_type": "ETF", "first_date": "2024-01-01",
                "last_date": "2026-01-01", "cumulative_return": cumulative, **extra}

    def test_lifetime_descending_ranking_ignores_one_year_return(self):
        us = [
            self.dated_etf("US_LOW", 10.0, cagr1y=40.0),
            self.dated_etf("US_HIGH", 100.0, cagr1y=-5.0),
            {"ticker": "STOCK", "asset_type": "주식", "cagr1y": 999},
        ]
        kr = [
            self.dated_etf("KR_MID", 50.0, cagr1y=999.0),
            self.dated_etf("KR_ZERO", 0.0, cagr1y=15.0),
            self.dated_etf("KR_NEW", 20.0, cagr1y=None,
                           inception="2025-07-01", first_date="2025-07-01"),
            self.dated_etf("KR_MISSING", None, cagr1y=1000.0),
        ]
        info = build_etf_info(us, kr)
        self.assertEqual([s["ticker"] for s in info["rows"]],
                         ["KR_NEW", "US_HIGH", "KR_MID", "US_LOW", "KR_ZERO"])
        self.assertEqual(info["pool"], 6)
        self.assertEqual(info["with_ret"], 5)

    def test_top_hundred_limit_preserves_descending_ranks_and_candidate_counts(self):
        etfs = [self.dated_etf(str(i), float(i)) for i in range(125)]
        info = build_etf_info(etfs, [])
        self.assertEqual(len(info["rows"]), 100)
        self.assertEqual([s["ticker"] for s in info["rows"]], list(map(str, range(124, 24, -1))))
        self.assertEqual((info["pool"], info["with_ret"]), (125, 125))

    def test_comparison_shows_all_six_return_metrics_in_order(self):
        row = {"ticker": "ETF", "name": "Example ETF", "market": "US",
               "cagr1y": 12.3, "cagr3y": 9.1, "cagr5y": 8.0, "cagr10y": 6.0,
               "cumulative_return": 159.4, "lifetime_cagr": 10.0,
               "inception": "2016-10-07", "lifetime_years": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        periods = re.findall(r'data-period="([^"]+)"', html)
        self.assertEqual(periods, ["1y", "3y", "5y", "10y", "cumulative", "lifetime"])
        for expected in [">12.3</span>", ">9.1</span>", ">8.0</span>", ">6.0</span>",
                         ">159.4</span>", ">10.0</span>"]:
            self.assertIn(expected, html)
        self.assertIn("연평균 누적수익률 내림차순", html)

    def test_missing_long_period_returns_keep_valid_cumulative_return(self):
        row = {"ticker": "NEW", "name": "New ETF", "cagr1y": 20.0,
               "cumulative_return": 30.0, "lifetime_cagr": 15.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn(">20.0</span>", html)
        self.assertIn(">30.0</span>", html)
        self.assertEqual(len(re.findall(r'<span[^>]*class="[^"]*flat[^"]*"[^>]*>-</span>', html)), 3)

    def test_missing_cumulative_return_is_shown_as_dash(self):
        row = {"ticker": "ETF", "name": "Example ETF", "cagr1y": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn('data-period="cumulative"', html)
        self.assertEqual(len(re.findall(r'<span[^>]*class="[^"]*flat[^"]*"[^>]*>-</span>', html)), 5)

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


class EtfLifetimeMetricTests(unittest.TestCase):
    @staticmethod
    def example(**extra):
        return {"ticker": "ETF", "asset_type": "ETF", "cumulative_return": 100.0,
                "inception": "2024-01-01", "first_date": "2024-01-02",
                "last_date": "2026-01-01", **extra}

    def test_two_year_doubling_is_compound_annualized(self):
        metrics = _etf_lifetime_metrics(self.example())
        self.assertAlmostEqual(metrics["lifetime_years"], 731 / 365.25)
        self.assertEqual(round(metrics["lifetime_cagr"], 1), 41.4)
        self.assertNotEqual(metrics["lifetime_cagr"], 100 / metrics["lifetime_years"])
        self.assertEqual(metrics["return_as_of"], "2026-01-01")

    def test_official_inception_controls_elapsed_years_before_first_price(self):
        metrics = _etf_lifetime_metrics(self.example(inception="2020-01-01"))
        expected_years = (date(2026, 1, 1) - date(2020, 1, 1)).days / 365.25
        self.assertEqual(metrics["inception"], "2020-01-01")
        self.assertEqual(metrics["lifetime_years"], expected_years)
        self.assertAlmostEqual(metrics["lifetime_cagr"], (2 ** (1 / expected_years) - 1) * 100)

    def test_missing_invalid_or_future_inception_uses_first_available_date(self):
        for inception in [None, "not-a-date", "2024-02-31", "2027-01-01", "2026-01-01"]:
            with self.subTest(inception=inception):
                metrics = _etf_lifetime_metrics(self.example(inception=inception))
                self.assertEqual(metrics["inception"], "2024-01-02")
                self.assertEqual(metrics["lifetime_years"], 730 / 365.25)

    def test_observed_last_close_date_controls_years(self):
        metrics = _etf_lifetime_metrics(self.example(inception="2020-01-01",
                                                   first_date="2020-01-02",
                                                   last_date="2022-01-01"))
        self.assertEqual(metrics["lifetime_years"], 731 / 365.25)
        self.assertEqual(round(metrics["lifetime_cagr"], 1), 41.4)
        self.assertEqual(metrics["return_as_of"], "2022-01-01")

    def test_less_than_one_year_is_annualized_and_eligible(self):
        item = self.example(inception="2025-07-01", first_date="2025-07-01",
                            cumulative_return=10.0, cagr1y=None)
        info = build_etf_info([item], [])
        self.assertEqual((info["pool"], info["with_ret"]), (1, 1))
        row = info["rows"][0]
        self.assertLess(row["lifetime_years"], 1)
        self.assertAlmostEqual(row["lifetime_cagr"], (1.1 ** (365.25 / 184) - 1) * 100)

    def test_zero_negative_and_total_loss_returns_are_valid(self):
        for cumulative, expected_sign in [(0.0, 0), (-20.0, -1), (-100.0, -1)]:
            with self.subTest(cumulative=cumulative):
                metrics = _etf_lifetime_metrics(self.example(cumulative_return=cumulative))
                self.assertIsNotNone(metrics)
                annualized = metrics["lifetime_cagr"]
                self.assertEqual((annualized > 0) - (annualized < 0), expected_sign)
        self.assertEqual(_etf_lifetime_metrics(self.example(cumulative_return=-100.0))["lifetime_cagr"], -100.0)

    def test_invalid_dates_order_and_missing_inputs_do_not_rank(self):
        changes = [{"last_date": None}, {"last_date": "2026-02-31"},
                   {"last_date": "2023-01-01"}, {"first_date": "2027-01-01"},
                   {"inception": None, "first_date": None},
                   {"inception": "bad", "first_date": "bad"},
                   {"inception": None, "first_date": "2026-01-01"},
                   {"cumulative_return": None}, {"cumulative_return": float("nan")},
                   {"cumulative_return": float("inf")}, {"cumulative_return": -100.1},
                   {"cumulative_return": True}, {"cumulative_growth": False},
                   {"cumulative_growth": float("inf")}, {"cumulative_growth": -0.1}]
        for changed in changes:
            with self.subTest(changed=changed):
                item = self.example(**changed)
                self.assertIsNone(_etf_lifetime_metrics(item))
                self.assertEqual(build_etf_info([item], [])["rows"], [])

    def test_unrounded_price_growth_controls_calculation_and_sort(self):
        dates = [date(2024, 1, 1), date(2026, 1, 1)]
        high = {"ticker": "HIGH", "asset_type": "ETF",
                **_etf_price_performance(dates, [100, 100.104])}
        low = {"ticker": "LOW", "asset_type": "ETF",
               **_etf_price_performance(dates, [100, 100.101])}
        self.assertEqual(high["cumulative_return"], low["cumulative_return"])
        self.assertNotEqual(high["cumulative_growth"], low["cumulative_growth"])
        info = build_etf_info([high, low], [])
        self.assertEqual([s["ticker"] for s in info["rows"]], ["HIGH", "LOW"])
        self.assertGreater(info["rows"][0]["lifetime_cagr"], info["rows"][1]["lifetime_cagr"])

    def test_price_metadata_retains_actual_first_and_last_observations(self):
        perf = _etf_price_performance([date(2024, 1, 2), date(2026, 1, 5)], [100, 200])
        self.assertEqual(perf["first_date"], "2024-01-02")
        self.assertEqual(perf["last_date"], "2026-01-05")
        self.assertEqual(perf["cumulative_growth"], 2.0)
        self.assertEqual(perf["cumulative_return"], 100.0)
        self.assertEqual(_etf_price_performance([], [])["last_date"], None)

    def test_ranking_does_not_mutate_collected_records(self):
        original = self.example(inception="invalid")
        before = dict(original)
        info = build_etf_info([original], [])
        self.assertEqual(original, before)
        self.assertEqual(info["rows"][0]["inception"], original["first_date"])
        self.assertNotIn("lifetime_cagr", original)


if __name__ == "__main__":
    unittest.main()

