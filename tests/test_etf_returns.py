"""Regression tests for cumulative ETF periods, lifetime CAGR, and email columns."""
import re
import unittest
from datetime import date, datetime, time
from unittest.mock import patch
from types import SimpleNamespace

from src.main import (_calc_perf, _etf_period_returns, _etf_price_performance, _etf_lifetime_metrics,
                      _validated_etf_metadata, _kr_etf_adjusted_performance,
                      build_etf_info, etf_section_html)


class EtfReturnTests(unittest.TestCase):
    def test_actual_mags_quotes_show_three_year_cumulative_not_cagr(self):
        # Quotes independently retrieved in Actions audit 40840310186.
        dates = [date(2023, 4, 11), date(2023, 10, 27), date(2025, 10, 28), date(2026, 10, 28)]
        prices = [23.82028579711914, 27.777029037475586, 67.3808364868164, 71.26000213623047]
        perf = _etf_price_performance(dates, prices)
        self.assertEqual(perf["return3y"], 156.5)
        self.assertEqual(perf["return1y"], 5.8)
        self.assertEqual(perf["cumulative_return"], 199.2)
        evidence = perf["period_returns"]["3y"]
        self.assertEqual(evidence["target_date"], "2023-10-28")
        self.assertEqual(evidence["start_date"], "2023-10-27")
        self.assertAlmostEqual(evidence["return_pct"], 156.54292271534695)
        self.assertNotEqual(perf["return3y"], round(((prices[-1] / prices[1]) ** (1 / 3) - 1) * 100, 1))

    def test_ytd_uses_preceding_year_close_and_preserves_exact_price_evidence(self):
        dates = [date(2024, 12, 31), date(2025, 12, 30), date(2026, 1, 2), date(2026, 10, 28)]
        prices = [80.0, 100.123456789, 110.0, 125.987654321]
        perf = _etf_price_performance(dates, prices)
        self.assertEqual(perf["return_ytd"], round((prices[-1] / prices[1] - 1) * 100, 1))
        evidence = perf["period_returns"]["ytd"]
        self.assertEqual(evidence["target_date"], "2025-12-31")
        self.assertEqual(evidence["start_date"], "2025-12-30")
        self.assertEqual(evidence["end_date"], "2026-10-28")
        self.assertEqual((evidence["start_price"], evidence["end_price"]), (prices[1], prices[-1]))

    def test_ytd_does_not_substitute_inception_or_first_new_year_quote(self):
        perf = _etf_price_performance([date(2026, 1, 2), date(2026, 10, 28)], [100, 150])
        self.assertIsNone(perf["return_ytd"])
        self.assertIsNone(perf["period_returns"]["ytd"])
        self.assertEqual(perf["cumulative_return"], 50.0)

    def test_stale_quote_near_year_boundary_uses_its_own_calendar_year(self):
        periods = _etf_period_returns([date(2024, 12, 30), date(2025, 12, 30)], [100, 120])
        self.assertEqual(periods["ytd"]["target_date"], "2024-12-31")
        self.assertEqual(periods["ytd"]["end_date"], "2025-12-30")
        self.assertEqual(periods["ytd"]["return_pct"], (120 / 100 - 1) * 100)

    def test_cumulative_returns_for_all_four_periods(self):
        dates = [date(2016, 10, 7), date(2021, 10, 7), date(2023, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        closes = [100, 161.051, 194.87171, 235.7947691, 259.37424601]
        self.assertEqual(_calc_perf(dates, closes),
                         (10.0, 33.1, 61.1, 159.4, 159.4, dates[0]))

    def test_exact_one_year_history_is_eligible(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 120]),
                         (20.0, None, None, None, 20.0, dates[0]))

    def test_exact_three_year_history_without_longer_periods(self):
        dates = [date(2023, 10, 7), date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 121, 133.1]),
                         (10.0, 33.1, None, None, 33.1, dates[0]))

    def test_exact_five_year_history_without_ten_year_history(self):
        dates = [date(2021, 10, 7), date(2023, 10, 7),
                 date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 121, 146.41, 161.051]),
                         (10.0, 33.1, 61.1, None, 61.1, dates[0]))

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
                         (10.0, 33.1, None, None, 33.1, dates[0]))

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
                         (10.0, 33.1, 61.1, None, None, dates[0]))

    def test_zero_and_negative_returns_are_valid(self):
        dates = [date(2025, 10, 7), date(2026, 10, 7)]
        self.assertEqual(_calc_perf(dates, [100, 100]),
                         (0.0, None, None, None, 0.0, dates[0]))
        self.assertEqual(_calc_perf(dates, [100, 90]),
                         (-10.0, None, None, None, -10.0, dates[0]))

    def test_cumulative_return_is_not_annualized(self):
        dates = [date(2016, 10, 7), date(2025, 10, 7), date(2026, 10, 7)]
        result = _calc_perf(dates, [100, 200, 200])
        self.assertEqual(result[3], 100.0)
        self.assertEqual(result[4], 100.0)


class EtfRankingAndHtmlTests(unittest.TestCase):
    @staticmethod
    def dated_etf(ticker, cumulative, **extra):
        return {"ticker": ticker, "asset_type": "ETF", "first_date": "2024-01-01",
                "last_date": "2026-01-01", "cumulative_return": cumulative, **extra}

    def test_lifetime_descending_ranking_ignores_one_year_return(self):
        us = [
            self.dated_etf("US_LOW", 10.0, return1y=40.0),
            self.dated_etf("US_HIGH", 100.0, return1y=-5.0),
            {"ticker": "STOCK", "asset_type": "주식", "return1y": 999},
        ]
        kr = [
            self.dated_etf("KR_MID", 50.0, return1y=999.0),
            self.dated_etf("KR_ZERO", 0.0, return1y=15.0),
            self.dated_etf("KR_NEW", 20.0, return1y=None,
                           inception="2025-07-01", first_date="2025-07-01"),
            self.dated_etf("KR_MISSING", None, return1y=1000.0),
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

    def test_comparison_shows_all_seven_return_metrics_in_order(self):
        row = {"ticker": "ETF", "name": "Example ETF", "market": "US",
               "return_ytd": 11.5, "return1y": 12.3, "return3y": 9.1, "return5y": 8.0, "return10y": 6.0,
               "cumulative_return": 159.4, "lifetime_cagr": 10.0,
               "inception": "2016-10-07", "lifetime_years": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        periods = re.findall(r'data-period="([^"]+)"', html)
        self.assertEqual(periods, ["ytd", "1y", "3y", "5y", "10y", "cumulative", "lifetime"])
        for expected in [">11.5</span>", ">12.3</span>", ">9.1</span>", ">8.0</span>", ">6.0</span>",
                         ">159.4</span>", ">10.0</span>"]:
            self.assertIn(expected, html)
        self.assertIn("연평균 누적수익률 내림차순", html)

    def test_missing_long_period_returns_keep_valid_cumulative_return(self):
        row = {"ticker": "NEW", "name": "New ETF", "return1y": 20.0,
               "cumulative_return": 30.0, "lifetime_cagr": 15.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn(">20.0</span>", html)
        self.assertIn(">30.0</span>", html)
        self.assertEqual(len(re.findall(r'<span[^>]*class="[^"]*flat[^"]*"[^>]*>-</span>', html)), 4)

    def test_missing_cumulative_return_is_shown_as_dash(self):
        row = {"ticker": "ETF", "name": "Example ETF", "return1y": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn('data-period="cumulative"', html)
        self.assertEqual(len(re.findall(r'<span[^>]*class="[^"]*flat[^"]*"[^>]*>-</span>', html)), 6)

    def test_footer_explains_cumulative_return_basis(self):
        row = {"ticker": "ETF", "name": "Example ETF", "return1y": 10.0}
        html = etf_section_html({"rows": [row], "pool": 1, "with_ret": 1})
        self.assertIn("(최근주가 ÷ 최초주가 - 1) × 100", html)
        self.assertIn("연환산하지 않음", html)
        self.assertIn("배당조정 미확인", html)

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
        self.assertAlmostEqual(metrics["lifetime_years"], 730 / 365.25)
        self.assertEqual(round(metrics["lifetime_cagr"], 1), 41.5)
        self.assertNotEqual(metrics["lifetime_cagr"], 100 / metrics["lifetime_years"])
        self.assertEqual(metrics["return_as_of"], "2026-01-01")

    def test_qqqm_displayed_lifetime_return_uses_exact_observed_days(self):
        item = self.example(first_date="2020-10-13", last_date="2026-10-27",
                            inception="2020-10-13", initial_adjusted_price=116.67774200439453,
                            latest_adjusted_price=296.9599914550781, cumulative_return=154.5)
        metrics = _etf_lifetime_metrics(item)
        self.assertEqual(metrics["lifetime_years"], 2205 / 365.25)
        self.assertAlmostEqual(metrics["lifetime_cagr"], 16.73587187, places=8)
        self.assertEqual(metrics["cumulative_return"], 154.5)
        self.assertNotEqual(metrics["lifetime_cagr"], 154.5 / metrics["lifetime_years"])

    def test_earlier_official_inception_does_not_inflate_actual_price_interval(self):
        metrics = _etf_lifetime_metrics(self.example(inception="2020-01-01"))
        expected_years = (date(2026, 1, 1) - date(2024, 1, 2)).days / 365.25
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
        self.assertEqual(metrics["lifetime_years"], 730 / 365.25)
        self.assertEqual(round(metrics["lifetime_cagr"], 1), 41.5)
        self.assertEqual(metrics["return_as_of"], "2022-01-01")

    def test_less_than_one_year_is_annualized_and_eligible(self):
        item = self.example(inception="2025-07-01", first_date="2025-07-01",
                            cumulative_return=10.0, return1y=None)
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
        perf = _etf_price_performance([date(2024, 1, 2), date(2026, 1, 5)], [100.123456789, 200.987654321],
                                      price_basis="Yahoo 제공 수정주가(auto_adjust)", price_currency="USD")
        self.assertEqual(perf["first_date"], "2024-01-02")
        self.assertEqual(perf["last_date"], "2026-01-05")
        self.assertEqual(perf["price_start_date"], "2024-01-02")
        self.assertEqual(perf["price_end_date"], "2026-01-05")
        self.assertEqual(perf["initial_adjusted_price"], 100.123456789)
        self.assertEqual(perf["latest_adjusted_price"], 200.987654321)
        self.assertEqual(perf["cumulative_growth"], 200.987654321 / 100.123456789)
        self.assertEqual(perf["cumulative_return"], round((200.987654321 / 100.123456789 - 1) * 100, 1))
        self.assertEqual(perf["price_basis"], "Yahoo 제공 수정주가(auto_adjust)")
        self.assertEqual(perf["price_currency"], "USD")
        self.assertEqual(_etf_price_performance([], [])["last_date"], None)

    def test_price_ratio_overrides_stale_rounded_cumulative_and_growth_metadata(self):
        item = self.example(
            initial_adjusted_price=23.123456789, latest_adjusted_price=42.987654321,
            cumulative_return=9999, cumulative_growth=9999)
        metrics = _etf_lifetime_metrics(item)
        growth = 42.987654321 / 23.123456789
        years = 730 / 365.25
        self.assertEqual(metrics["cumulative_return"], round((growth - 1) * 100, 1))
        self.assertAlmostEqual(metrics["lifetime_cagr"], (growth ** (1 / years) - 1) * 100)
        # Integer display must not replace the exact prices used for calculation.
        self.assertNotEqual(metrics["cumulative_return"], round((42 / 23 - 1) * 100, 1))
        self.assertEqual((item["initial_adjusted_price"], item["latest_adjusted_price"]),
                         (23.123456789, 42.987654321))

    def test_one_missing_or_invalid_verification_price_does_not_rank(self):
        for changes in [{"initial_adjusted_price": 100}, {"latest_adjusted_price": 200},
                        {"initial_adjusted_price": 0, "latest_adjusted_price": 200},
                        {"initial_adjusted_price": 100, "latest_adjusted_price": float("nan")},
                        {"initial_adjusted_price": True, "latest_adjusted_price": 200}]:
            with self.subTest(changes=changes):
                self.assertIsNone(_etf_lifetime_metrics(self.example(**changes)))

    def test_late_vendor_inception_is_rejected_when_price_history_is_older(self):
        item = self.example(inception="2025-12-20")
        corrected = _validated_etf_metadata(item)
        self.assertEqual(corrected["inception"], item["first_date"])
        self.assertEqual(corrected["rejected_inception"], "2025-12-20")
        self.assertFalse(corrected["inception_verified"])
        self.assertIn("미확인", corrected["inception_source"])
        metrics = _etf_lifetime_metrics(item)
        self.assertEqual(metrics["lifetime_years"], 730 / 365.25)

    def test_coherent_sourced_vendor_inception_is_cross_checked_but_fallback_is_not(self):
        for source in ["Yahoo fundInceptionDate(가격이력 교차검증)", "네이버 ETF 공시 상장일(가격이력 교차검증)"]:
            with self.subTest(source=source):
                item = self.example(inception_source=source, inception_verified=False)
                corrected = _validated_etf_metadata(item)
                self.assertTrue(corrected["inception_verified"])
                self.assertEqual(corrected["inception"], "2024-01-01")
                self.assertTrue(_etf_lifetime_metrics(item)["inception_verified"])
        fallback = self.example(inception=None)
        corrected = _validated_etf_metadata(fallback)
        self.assertFalse(corrected["inception_verified"])
        self.assertIn("미확인", corrected["inception_source"])
        self.assertFalse(_validated_etf_metadata(corrected)["inception_verified"])

    def test_dfac_reorganization_is_not_used_as_original_etf_inception(self):
        dates = [date(2007, 10, 4), date(2021, 6, 14), date(2021, 10, 14), date(2026, 10, 14)]
        perf = _etf_price_performance(dates, [10, 20, 22, 40], not_before="2021-06-14",
                                      price_basis="Yahoo 제공 수정주가(auto_adjust)", price_currency="USD")
        item = {"ticker": "DFAC", "asset_type": "ETF", "market": "US",
                "inception": "2026-10-02", **perf}
        corrected = _validated_etf_metadata(item)
        self.assertEqual(corrected["inception"], "2021-06-14")
        self.assertEqual(corrected["inception_label"], "ETF 최초상장일")
        self.assertEqual(corrected["predecessor_inception"], "2007-10-04")
        self.assertEqual(corrected["current_portfolio_inception"], "2005-09-15")
        self.assertEqual(corrected["share_class_reorganization"], "2026-10-02")
        self.assertTrue(corrected["inception_verified"])
        self.assertIsNotNone(perf["return5y"])
        self.assertIsNone(perf["return10y"])
        self.assertEqual((perf["initial_adjusted_price"], perf["latest_adjusted_price"]), (20, 40))
        metrics = _etf_lifetime_metrics(item)
        self.assertEqual(metrics["cumulative_return"], 100.0)
        self.assertEqual(metrics["lifetime_years"], (dates[-1] - dates[1]).days / 365.25)

    def test_verified_dfac_launch_rejects_unfiltered_predecessor_price_history(self):
        item = self.example(ticker="DFAC", market="US", first_date="2007-10-04",
                            inception="2026-10-02")
        self.assertIsNone(_etf_lifetime_metrics(item))

    def test_ranking_does_not_mutate_collected_records(self):
        original = self.example(inception="invalid")
        before = dict(original)
        info = build_etf_info([original], [])
        self.assertEqual(original, before)
        self.assertEqual(info["rows"][0]["inception"], original["first_date"])
        self.assertNotIn("lifetime_cagr", original)


class KoreanAdjustedHistoryTests(unittest.TestCase):
    @staticmethod
    def fake_history(dates, prices):
        series = SimpleNamespace(index=[datetime.combine(day, time()) for day in dates],
                                 tolist=lambda: prices)
        series.dropna = lambda: series
        return {"Close": series}

    def test_fresh_complete_adjusted_history_is_accepted_with_exact_prices(self):
        dates = [date(2021, 1, 4), date(2026, 10, 14)]
        fallback = {"first_date": "2021-01-04", "last_date": "2026-10-14"}
        history = self.fake_history(dates, [9876.54321, 20000.25])
        with patch("src.main.yf.Ticker") as ticker:
            ticker.return_value.history.return_value = history
            result = _kr_etf_adjusted_performance("123456", "KOSPI", fallback)
            ticker.assert_called_once_with("123456.KS")
            ticker.return_value.history.assert_called_once_with(period="max", auto_adjust=True, timeout=12)
        self.assertEqual(result["initial_adjusted_price"], 9876.54321)
        self.assertEqual(result["latest_adjusted_price"], 20000.25)
        self.assertEqual(result["price_currency"], "KRW")
        self.assertEqual(result["price_basis"], "Yahoo 제공 수정주가(auto_adjust)")

    def test_stale_short_invalid_or_unavailable_adjusted_series_does_not_replace_naver(self):
        fallback = {"first_date": "2021-01-04", "last_date": "2026-10-14"}
        examples = [([date(2021, 1, 4), date(2026, 10, 13)], [100, 200]),
                    ([date(2022, 1, 4), date(2026, 10, 14)], [100, 200]),
                    ([date(2021, 1, 4), date(2026, 10, 14)], [100, float("nan")]),
                    ([date(2026, 10, 14)], [100])]
        for dates, prices in examples:
            with self.subTest(dates=dates, prices=prices), patch("src.main.yf.Ticker") as ticker:
                ticker.return_value.history.return_value = self.fake_history(dates, prices)
                self.assertIsNone(_kr_etf_adjusted_performance("123456", "KOSDAQ", fallback))
                ticker.assert_called_once_with("123456.KQ")
        with patch("src.main.yf.Ticker", side_effect=RuntimeError("unavailable")):
            self.assertIsNone(_kr_etf_adjusted_performance("123456", "KOSPI", fallback))


if __name__ == "__main__":
    unittest.main()
