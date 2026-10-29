"""ETF market-date integrity before calculation, preparation, and SMTP."""
import copy
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.main import (_etf_price_performance, build_etf_info, main,
                      get_trading_info, synchronize_etf_market_dates, validate_etf_market_dates)


def market_info(us_day="2026-10-28", kr_day="2026-10-28"):
    return {"us_last": date.fromisoformat(us_day), "kr_last": date.fromisoformat(kr_day),
            "us_last_str": us_day, "kr_last_str": kr_day,
            "us_holiday": False, "kr_holiday": False,
            "us_holiday_msg": "", "kr_holiday_msg": ""}


def etf(ticker="QQQM", market="US", end="2026-10-28", latest=260.0):
    item = {"ticker": ticker, "asset_type": "ETF", "market": market,
            "name": ticker, "inception": "2020-10-13", "mcap": 1.0,
            "price": latest, "gap": -1.0, "change": 1.0,
            "index": ["NASDAQ" if market == "US" else "KOSPI"],
            "url": "https://example.test/" + ticker}
    item.update(_etf_price_performance(
        [date(2020, 10, 13), date.fromisoformat(end)], [100.0, latest],
        price_basis="Yahoo 제공 수정주가(auto_adjust)",
        price_currency="USD" if market == "US" else "KRW"))
    return item


def yahoo_history(days, prices):
    return pd.DataFrame({"Close": prices}, index=pd.to_datetime(days))


class MarketDateValidationTests(unittest.TestCase):
    def test_market_anchors_exclude_today_partial_quotes_and_respect_korean_holiday(self):
        histories = {"SPY": yahoo_history(["2026-10-27", "2026-10-28", "2026-10-29"], [100, 101, 999]),
                     "005930.KS": yahoo_history(["2026-10-26", "2026-10-27", "2026-10-29"], [100, 101, 999])}
        with patch("src.main.datetime") as clock, patch("src.main.yf.Ticker") as ticker:
            clock.now.return_value = datetime(2026, 10, 29, 12, 0)
            ticker.side_effect = lambda symbol: SimpleNamespace(history=lambda **kwargs: histories[symbol])
            info = get_trading_info()
        self.assertEqual(info["expected"], date(2026, 10, 28))
        self.assertEqual(info["us_last"], date(2026, 10, 28))
        self.assertEqual(info["kr_last"], date(2026, 10, 27))
        self.assertFalse(info["us_holiday"])
        self.assertTrue(info["kr_holiday"])

    def test_each_market_uses_its_own_trading_calendar_without_mutating_candidates(self):
        us = [etf(end="2026-10-28")]
        kr = [etf("123456", "KOSPI", end="2026-10-27")]
        before = copy.deepcopy((us, kr))
        proof = validate_etf_market_dates(us, kr, market_info(kr_day="2026-10-27"))
        self.assertIsInstance(proof, dict)
        self.assertEqual((us, kr), before)

    def test_latest_available_price_date_is_truthfully_audited_without_forward_dating(self):
        item = etf(end="2026-10-27", latest=254.5)
        before = copy.deepcopy(item)
        proof = validate_etf_market_dates([item], [], market_info())
        record = proof["etfs"][0]
        self.assertEqual(proof["version"], 2)
        self.assertEqual(record["date_status"], "latest_available")
        self.assertEqual(record["requested_market_date"], "2026-10-28")
        self.assertEqual(record["return_as_of"], "2026-10-27")
        self.assertEqual(record["price_end_date"], "2026-10-27")
        self.assertEqual(record["lifetime_years"], 2205 / 365.25)
        self.assertEqual(item, before)

    def test_missing_invalid_and_future_observation_dates_are_rejected(self):
        for value in (None, "2026-02-30", "not-a-date", "2026-10-29"):
            with self.subTest(price_end_date=value):
                item = etf()
                item["price_end_date"] = value
                item["last_date"] = value
                with self.assertRaises(RuntimeError):
                    validate_etf_market_dates([item], [], market_info())

    def test_copying_the_requested_date_over_an_older_observation_is_rejected(self):
        item = etf(end="2026-10-27")
        item["price_end_date"] = "2026-10-28"
        with self.assertRaises(RuntimeError):
            validate_etf_market_dates([item], [], market_info())

    def test_every_candidate_is_checked_including_etfs_outside_the_top_hundred(self):
        candidates = [etf("ETF%03d" % index, latest=1000.0-index) for index in range(101)]
        stale = etf("STALE_OUTSIDE_TOP_100", end="2026-10-27", latest=100.01)
        candidates.append(stale)
        self.assertNotIn(stale["ticker"], [row["ticker"] for row in build_etf_info(candidates, [])["rows"]])
        proof = validate_etf_market_dates(candidates, [], market_info())
        self.assertEqual(len(proof["etfs"]), 102)
        audited = next(row for row in proof["etfs"] if row["ticker"] == stale["ticker"])
        self.assertEqual((audited["date_status"], audited["price_end_date"]), ("latest_available", "2026-10-27"))
        stale.update(price_end_date="2026-10-29", last_date="2026-10-29")
        with self.assertRaises(RuntimeError):
            validate_etf_market_dates(candidates, [], market_info())
        self.assertEqual(len(candidates), 102)

    def test_missing_market_date_fails_when_that_market_has_an_etf(self):
        for value in (None, "bad", "2026-02-30"):
            info = market_info()
            info["us_last"] = value
            with self.subTest(market_date=value), self.assertRaises(RuntimeError):
                validate_etf_market_dates([etf()], [], info)


class MarketDateSynchronizationTests(unittest.TestCase):
    def test_stale_history_is_refetched_and_future_partial_session_is_trimmed(self):
        item = etf(end="2026-10-27", latest=254.5)
        candidates = [item, {"ticker": "STOCK", "asset_type": "주식", "market": "US"}]
        before_ids = [id(row) for row in candidates]
        history = yahoo_history(["2020-10-13", "2026-10-27", "2026-10-28", "2026-10-29"],
                                [100.0, 254.5, 260.0, 999.0])
        with patch("src.main.yf.Ticker") as ticker:
            ticker.return_value.history.return_value = history
            synchronize_etf_market_dates(candidates, [], market_info(), attempts=2)
            self.assertTrue(ticker.return_value.history.called)
            self.assertEqual(ticker.return_value.history.call_args.kwargs["end"], "2026-10-29")
        self.assertEqual([id(row) for row in candidates], before_ids)
        self.assertEqual([row["ticker"] for row in candidates], ["QQQM", "STOCK"])
        self.assertEqual(item["price_end_date"], "2026-10-28")
        self.assertEqual(item["last_date"], "2026-10-28")
        self.assertEqual(item["price_start_date"], "2020-10-13")
        self.assertEqual((item["initial_adjusted_price"], item["latest_adjusted_price"]), (100.0, 260.0))
        self.assertEqual(item["cumulative_return"], 160.0)
        self.assertEqual(item["gap"], 0.0)
        self.assertIsInstance(validate_etf_market_dates(candidates, [], market_info()), dict)

    def test_fresh_candidates_do_not_trigger_network_or_alter_calculation(self):
        us, kr = [etf()], [etf("123456", "KOSPI")]
        before = copy.deepcopy((us, kr))
        expected_cagr = build_etf_info(us, kr)["rows"][0]["lifetime_cagr"]
        with patch("src.main.yf.Ticker") as ticker:
            synchronize_etf_market_dates(us, kr, market_info(), attempts=2)
            ticker.assert_not_called()
        for current, original in zip(us + kr, before[0] + before[1]):
            for key, value in original.items():
                self.assertEqual(current[key], value)
        self.assertEqual(build_etf_info(us, kr)["rows"][0]["lifetime_cagr"], expected_cagr)

    def test_two_older_provider_replies_keep_the_newer_existing_history(self):
        item = etf(end="2026-10-27", latest=254.5)
        before = copy.deepcopy(item)
        with patch("src.main.yf.Ticker") as ticker, patch("src.main.time.sleep"):
            ticker.return_value.history.return_value = yahoo_history(["2020-10-13", "2026-10-26"], [100, 200])
            proof = synchronize_etf_market_dates([item], [], market_info(), attempts=2)
            self.assertEqual(ticker.return_value.history.call_count, 2)
        for key, value in before.items():
            self.assertEqual(item[key], value)
        self.assertEqual(proof["etfs"][0]["date_status"], "latest_available")
        self.assertEqual(proof["etfs"][0]["price_end_date"], "2026-10-27")

    def test_korean_naver_history_keeps_its_provider_and_excludes_future_partial_prices(self):
        item = etf("123456", "KOSPI", end="2026-10-27", latest=254.5)
        item["price_basis"] = "네이버 차트 종가·배당조정 미확인"
        dates = [date(2020, 10, 13), date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)]
        with patch("src.main._kr_price_history_dated", return_value=(dates, [100, 254.5, 260, 999])) as naver, \
                patch("src.main.yf.Ticker") as yahoo:
            synchronize_etf_market_dates([], [item], market_info(), attempts=2)
            naver.assert_called_once_with("123456", count=8000)
            yahoo.assert_not_called()
        self.assertEqual((item["price_end_date"], item["latest_adjusted_price"]), ("2026-10-28", 260.0))
        self.assertEqual(item["price_basis"], "네이버 차트 종가·배당조정 미확인")
        self.assertEqual(item["price_currency"], "KRW")

    def test_refetch_cannot_silently_discard_known_initial_history(self):
        item = etf(end="2026-10-27", latest=254.5)
        before = copy.deepcopy(item)
        with patch("src.main.yf.Ticker") as ticker, patch("src.main.time.sleep"):
            ticker.return_value.history.return_value = yahoo_history(["2021-10-13", "2026-10-28"], [100, 260])
            proof = synchronize_etf_market_dates([item], [], market_info(), attempts=2)
            self.assertEqual(ticker.return_value.history.call_count, 2)
        for key, value in before.items():
            self.assertEqual(item[key], value)
        self.assertEqual(proof["etfs"][0]["date_status"], "latest_available")

    def test_dfac_refetch_filters_pre_etf_observations_and_clears_obsolete_mismatch_flag(self):
        item = etf("DFAC", end="2026-10-27", latest=35.0)
        item.update(_etf_price_performance([date(2021, 6, 14), date(2026, 10, 27)], [20, 35],
                                           price_basis="Yahoo 제공 수정주가(auto_adjust)", price_currency="USD"))
        item.update(inception="2026-10-02", price_history_inception_mismatch=True)
        with patch("src.main.yf.Ticker") as ticker:
            ticker.return_value.history.return_value = yahoo_history(["2007-10-04", "2021-06-14", "2026-10-28"],
                                                                    [10, 20, 40])
            synchronize_etf_market_dates([item], [], market_info(), attempts=2)
        self.assertEqual(item["price_start_date"], "2021-06-14")
        self.assertEqual(item["price_end_date"], "2026-10-28")
        self.assertEqual(item["inception"], "2021-06-14")
        self.assertFalse(item.get("price_history_inception_mismatch", False))
        self.assertEqual((item["initial_adjusted_price"], item["latest_adjusted_price"]), (20, 40))
        self.assertIsNotNone(item["cagr5y"])
        self.assertIsNone(item["cagr10y"])

    def test_failed_retry_sends_valid_previous_prices_without_dropping_the_candidate(self):
        item = etf(end="2026-10-27", latest=254.5)
        candidates, before = [item], copy.deepcopy(item)
        with (patch("src.main.get_trading_info", return_value=market_info()),
              patch("src.main.get_usd_krw", return_value=1342),
              patch("src.main.get_market_indices", return_value={}),
              patch("src.main.get_us_ath", return_value=candidates),
              patch("src.main.get_kr_ath", return_value=[]),
              patch("src.main.yf.Ticker") as ticker,
              patch("src.main.time.sleep"),
              patch("src.main.send_email") as send,
              patch("src.main.smtplib.SMTP_SSL") as smtp,
              patch("src.main.load_snapshots", return_value={}) as load,
              patch("src.main.save_snapshots") as save):
            ticker.return_value.history.side_effect = RuntimeError("price provider unavailable")
            main()
            self.assertGreaterEqual(ticker.return_value.history.call_count, 2)
            send.assert_called_once()
            smtp.assert_not_called()
            load.assert_called_once()
            save.assert_called_once()
            self.assertIn("26-10-27", send.call_args.args[0])
            self.assertIn("2026-10-27", send.call_args.args[0])
        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0], item)
        for key in ("ticker", "price_start_date", "price_end_date", "initial_adjusted_price",
                    "latest_adjusted_price", "cumulative_return"):
            self.assertEqual(item[key], before[key])

    def test_no_usable_history_preserves_candidate_but_never_fabricates_a_return(self):
        item = {"ticker":"NO_HISTORY", "asset_type":"ETF", "market":"US", "name":"No history",
                "price":123.0, "change":1.0, "gap":-2.0, "mcap":1.0}
        candidates = [item]
        with patch("src.main.yf.Ticker") as ticker, patch("src.main.time.sleep"):
            ticker.return_value.history.side_effect = RuntimeError("provider unavailable")
            proof = synchronize_etf_market_dates(candidates, [], market_info(), attempts=2)
        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0], item)
        self.assertEqual(proof["etfs"][0]["date_status"], "unavailable")
        for key in ("price", "change", "gap", "cagr1y", "cagr3y", "cagr5y", "cagr10y",
                    "cumulative_return", "cumulative_growth", "lifetime_cagr", "lifetime_years",
                    "price_start_date", "price_end_date", "first_date", "last_date", "return_as_of",
                    "initial_adjusted_price", "latest_adjusted_price"):
            self.assertIsNone(item.get(key), key)
        self.assertEqual(build_etf_info(candidates, []), {"rows":[], "pool":1, "with_ret":0})
        mixed = dict(item, latest_adjusted_price=123.0)
        with self.assertRaises(RuntimeError):
            validate_etf_market_dates([mixed], [], market_info())


if __name__ == "__main__":
    unittest.main()
