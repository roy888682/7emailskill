"""Complete Korean ETF pagination and independent comparison regressions."""
from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.main import (get_kr_etf_universe, get_kr_ath, build_etf_info,
                      validate_etf_market_dates)


FUNDS = {
    "225040": "TIGER 미국S&P500레버리지(합성 H)",
    "418660": "TIGER 미국나스닥100레버리지(합성)",
    "409820": "KODEX 미국나스닥100레버리지(합성 H)",
}


def row(code, name=None):
    return {"itemcode": code, "itemname": name or FUNDS.get(code, "TIGER 테스트 " + code),
            "totalNetAssets": "50000000000", "etfType": "해외주식"}


def response(index, codes, total, has_next, *, status=200):
    data = {"items": [row(code) for code in codes], "index": str(index),
            "size": "100", "totalCount": str(total), "hasNext": has_next}
    return SimpleNamespace(status_code=status, text="synthetic ETF page", json=lambda: data)


class KoreanEtfUniverseTests(unittest.TestCase):
    def test_walks_page_numbers_and_short_nonterminal_pages_until_has_next_is_false(self):
        # A short page is not evidence of completion: only hasNext/totalCount
        # establish that every candidate was collected, including later pages.
        pages = [response(0, ["111111", "225040"], 5, True),
                 response(1, ["418660"], 5, True),
                 response(2, ["409820", "0167A0"], 5, False)]
        with patch("src.main.requests.get", side_effect=pages) as request, patch("src.main.time.sleep"):
            result = get_kr_etf_universe()
        self.assertEqual(set(result), {"111111", "225040", "418660", "409820", "0167A0"})
        self.assertEqual([call.kwargs["params"]["index"] for call in request.call_args_list], [0, 1, 2])
        self.assertTrue(all(call.kwargs["params"]["size"] == 100 for call in request.call_args_list))
        for code, name in FUNDS.items():
            self.assertEqual(result[code]["name"], name)
            self.assertTrue(result[code]["is_etf"])
            self.assertEqual(result[code]["aum"], .05)
            self.assertEqual(result[code]["investment_area"], "해외주식")

    def test_recovers_transient_failure_without_skipping_the_failed_page(self):
        pages = [response(0, ["225040"], 2, True),
                 response(1, [], 2, False, status=503),
                 response(1, ["418660"], 2, False)]
        with patch("src.main.requests.get", side_effect=pages) as request, patch("src.main.time.sleep"):
            result = get_kr_etf_universe()
        self.assertEqual(set(result), {"225040", "418660"})
        self.assertEqual([call.kwargs["params"]["index"] for call in request.call_args_list], [0, 1, 1])

    def test_deduplicates_overlapping_pages_when_the_final_unique_count_is_complete(self):
        with (patch("src.main.requests.get", side_effect=[
                response(0, ["225040", "418660"], 3, True),
                response(1, ["418660", "409820"], 3, False)]),
              patch("src.main.time.sleep")):
            self.assertEqual(set(get_kr_etf_universe()), set(FUNDS))

    def test_partial_last_page_is_retried_then_rejected_instead_of_silently_omitting_funds(self):
        pages = [response(0, ["225040"], 3, True)] + [response(1, ["418660"], 3, False)] * 3
        with patch("src.main.requests.get", side_effect=pages) as request, patch("src.main.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, r"page=1.*1.*3.*incomplete: 2/3"):
                get_kr_etf_universe()
        self.assertEqual(request.call_count, 4)

    def test_repeated_page_with_no_new_security_is_bounded_and_rejected(self):
        pages = [response(0, ["225040"], 3, True)] + [response(1, ["225040"], 3, True)] * 3
        with patch("src.main.requests.get", side_effect=pages) as request, patch("src.main.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "without progress"):
                get_kr_etf_universe()
        self.assertEqual(request.call_count, 4)

    def test_wrong_page_or_changed_total_is_not_accepted_as_a_complete_universe(self):
        for bad in (response(0, ["418660"], 2, False), response(1, ["418660"], 3, True)):
            with self.subTest(bad=bad.json()), patch("src.main.requests.get", side_effect=[
                    response(0, ["225040"], 2, True), bad, bad, bad]), patch("src.main.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "page index or total count changed"):
                    get_kr_etf_universe()

    def test_invalid_metadata_or_rows_receive_only_three_attempts(self):
        valid = response(0, ["225040"], 1, False).json()
        changes = [{"hasNext": "false"}, {"totalCount": True}, {"index": "wrong"},
                   {"items": None}, {"items": [row("bad")]},
                   {"items": [row("225040"), row("225040")]},
                   {"items": [], "hasNext": True}]
        for change in changes:
            bad = SimpleNamespace(status_code=200, json=lambda value=dict(valid, **change): value)
            with self.subTest(change=change), patch("src.main.requests.get", return_value=bad) as request, \
                    patch("src.main.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "page=0"):
                    get_kr_etf_universe()
                self.assertEqual(request.call_count, 3)

    def test_empty_verified_inventory_is_distinct_from_an_incomplete_response(self):
        with patch("src.main.requests.get", return_value=response(0, [], 0, False)) as request:
            self.assertEqual(get_kr_etf_universe(), {})
        request.assert_called_once()

    def test_page_safety_limit_prevents_an_unbounded_provider_loop(self):
        def many_pages(*args, **kwargs):
            index = kwargs["params"]["index"]
            return response(index, [f"{index:06d}"], 10000, True)
        with patch("src.main.requests.get", side_effect=many_pages) as request, patch("src.main.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "페이지 안전 한도 초과"):
                get_kr_etf_universe()
        self.assertEqual(request.call_count, 100)

    def test_all_three_leveraged_funds_enter_general_cagr_comparison_without_ath_exceptions(self):
        with patch("src.main.requests.get", side_effect=[
                response(0, ["225040"], 3, True), response(1, ["418660"], 3, True),
                response(2, ["409820"], 3, False)]), patch("src.main.time.sleep"):
            universe = get_kr_etf_universe()
        starts = {"225040": date(2015, 7, 29), "418660": date(2022, 2, 22),
                  "409820": date(2021, 12, 9)}
        prices = {"225040": [100, 1000, 650], "418660": [100, 500, 370], "409820": [100, 250, 186]}
        histories = {code: ([starts[code], date(2025, 12, 31), date(2026, 11, 2)], prices[code])
                     for code in FUNDS}
        histories["005930"] = ([date(2026, 10, 4) + timedelta(days=i) for i in range(30)], [100] * 30)
        pool = []
        with (patch("src.main.get_kr_universe", return_value={"005930": {
                    "name": "삼성전자", "market": "KOSPI", "mcap": 1}}),
              patch("src.main.get_kr_etf_universe", return_value=universe),
              patch("src.main._kr_price_history_dated", side_effect=lambda code, **kw: histories[code]),
              patch("src.main.fetch_kr_etf_base", return_value=None),
              patch("src.main._kr_etf_adjusted_performance", return_value=None)):
            ath = get_kr_ath(1400, date(2026, 11, 2), pool)
        self.assertEqual([item["ticker"] for item in ath], ["005930"])
        self.assertEqual({item["ticker"] for item in pool}, set(FUNDS))
        self.assertTrue(all(item["gap"] < -10 for item in pool))
        comparison = build_etf_info([], ath, pool)
        self.assertEqual([item["ticker"] for item in comparison["rows"]], ["418660", "225040", "409820"])
        proof = validate_etf_market_dates([], ath, {"us_last": date(2026, 11, 2),
                                                   "kr_last": date(2026, 11, 2)}, pool)
        self.assertEqual(proof["comparison_universe"], ["KR:" + code for code in sorted(FUNDS)])
        self.assertTrue(all(not item["in_ath_report"] and item["in_comparison_universe"] for item in proof["etfs"]))


if __name__ == "__main__":
    unittest.main()
