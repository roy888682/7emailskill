"""Complete Korean ETF full-list decoding and comparison regressions."""
from datetime import date, timedelta
from types import SimpleNamespace
import json
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
            "marketSum": 500, "etfTabCode": 4}


def catalog(codes=None):
    if codes is None:
        codes = list(FUNDS) + ["0167A0"] + [f"{i:06d}" for i in range(100000, 101184)]
    return {"resultCode": "success", "result": {"etfItemList": [row(code) for code in codes]}}


def response(data=None, *, status=200, codec="cp949"):
    data = catalog() if data is None else data
    return SimpleNamespace(status_code=status, content=json.dumps(data, ensure_ascii=False).encode(codec))


class KoreanEtfUniverseTests(unittest.TestCase):
    def test_whole_cp949_inventory_preserves_all_rows_names_and_alphanumeric_codes(self):
        with patch("src.main.requests.get", return_value=response()) as request:
            result = get_kr_etf_universe()
        self.assertEqual(len(result), 1188)
        self.assertIn("0167A0", result)
        self.assertIn("101183", result)
        request.assert_called_once_with("https://finance.naver.com/api/sise/etfItemList.nhn",
                                        headers=unittest.mock.ANY, timeout=20)
        for code, name in FUNDS.items():
            self.assertEqual(result[code]["name"], name)
            self.assertTrue(result[code]["is_etf"])
            self.assertEqual(result[code]["mcap"], .05)
            self.assertIsNone(result[code]["aum"])

    def test_also_decodes_utf8_without_corrupting_korean_names(self):
        with patch("src.main.requests.get", return_value=response(codec="utf-8")):
            self.assertEqual(get_kr_etf_universe()["409820"]["name"], FUNDS["409820"])

    def test_recovers_transient_failure_by_retrying_the_entire_inventory(self):
        with patch("src.main.requests.get", side_effect=[response(status=503), response()]) as request, \
                patch("src.main.time.sleep"):
            result = get_kr_etf_universe()
        self.assertEqual(len(result), 1188)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all("params" not in call.kwargs for call in request.call_args_list))

    def test_empty_or_100_or_300_row_inventory_is_retried_and_never_returned(self):
        for size in (0, 100, 300):
            bad = catalog([f"{i:06d}" for i in range(size)])
            with self.subTest(size=size), patch("src.main.requests.get", return_value=response(bad)) as request, \
                    patch("src.main.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "inventory is incomplete"):
                    get_kr_etf_universe()
                self.assertEqual(request.call_count, 3)

    def test_duplicate_codes_are_rejected_even_when_the_array_is_large(self):
        data = catalog()
        data["result"]["etfItemList"][-1] = row("225040")
        with patch("src.main.requests.get", return_value=response(data)) as request, patch("src.main.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "invalid or duplicate"):
                get_kr_etf_universe()
        self.assertEqual(request.call_count, 3)

    def test_malformed_metadata_and_every_bad_row_are_rejected(self):
        bad_data = [{}, {"resultCode": "error"}, {"resultCode": "success", "result": {"etfItemList": None}},
                    {"items": [row("225040")], "hasNext": True, "totalCount": 1188}]
        for bad_row in (None, row("bad"), row("123 45"), row("225040", "   "),
                        {"itemcode": "101183", "itemname": None}):
            data = catalog()
            data["result"]["etfItemList"][-1] = bad_row
            bad_data.append(data)
        for data in bad_data:
            with self.subTest(data=str(data)[:100]), patch("src.main.requests.get", return_value=response(data)) as request, \
                    patch("src.main.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "한국 ETF 전체 목록 수집 실패"):
                    get_kr_etf_universe()
                self.assertEqual(request.call_count, 3)

    def test_invalid_json_and_persistent_http_failures_are_bounded(self):
        for bad in (SimpleNamespace(status_code=200, content=b"<html>unavailable</html>"), response(status=404)):
            with self.subTest(status=bad.status_code), patch("src.main.requests.get", return_value=bad) as request, \
                    patch("src.main.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "한국 ETF 전체 목록 수집 실패"):
                    get_kr_etf_universe()
                self.assertEqual(request.call_count, 3)

    def test_market_cap_units_are_not_misrepresented_as_raw_won_aum(self):
        data = catalog()
        data["result"]["etfItemList"][0]["marketSum"] = "205,525"
        data["result"]["etfItemList"][1]["marketSum"] = None
        with patch("src.main.requests.get", return_value=response(data)):
            result = get_kr_etf_universe()
        self.assertEqual(result["225040"]["mcap"], 20.5525)
        self.assertIsNone(result["225040"]["aum"])
        self.assertIsNone(result["418660"]["mcap"])

    def test_late_malformed_row_is_not_silently_skipped(self):
        data = catalog()
        data["result"]["etfItemList"][-1] = {"itemcode": "101183"}
        with patch("src.main.requests.get", return_value=response(data)), patch("src.main.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "invalid or duplicate"):
                get_kr_etf_universe()

    def test_all_three_leveraged_funds_enter_general_cagr_comparison_without_ath_exceptions(self):
        with patch("src.main.requests.get", return_value=response(catalog(list(FUNDS)))), \
                patch("src.main._KR_ETF_CATALOG_MINIMUM", 3):
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
