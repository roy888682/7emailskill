import unittest
from datetime import date
from unittest.mock import Mock, patch

from src import us_naver_links as links


class NaverUSLinkTests(unittest.TestCase):
    def setUp(self):
        links.resolve_us_url.cache_clear()

    def test_official_search_urls_preserve_routes_and_reuters_codes(self):
        # Public ac.stock.naver.com responses verified on 2026-10-09.
        cases = (
            ("VZ", "NYSE", "/worldstock/stock/VZ/total"),
            ("NVDA", "NASDAQ", "/worldstock/stock/NVDA.O/total"),
            ("TQQQ", "NASDAQ", "/worldstock/etf/TQQQ.O"),
            ("SPY", "AMEX", "/worldstock/etf/SPY"),
            ("SMH", "NASDAQ", "/worldstock/etf/SMH.O"),
        )
        for ticker, exchange, url in cases:
            with self.subTest(ticker=ticker):
                payload = {"items": [{"code": ticker, "nationCode": "USA",
                                      "typeCode": exchange, "url": url}]}
                self.assertEqual(links.matching_url(payload, ticker), links.NAVER_ORIGIN + url)

    def test_similar_symbols_other_countries_and_untrusted_urls_are_rejected(self):
        payload = {"items": [
            {"code": "SPYD", "nationCode": "USA", "url": "/worldstock/etf/SPYD.K"},
            {"code": "SPY", "nationCode": "KOR", "url": "/domestic/stock/SPY"},
            {"code": "SPY", "nationCode": "USA", "url": "https://example.com/worldstock/etf/SPY"},
            {"code": "SPY", "nationCode": "USA", "url": "https://m.stock.naver.com.evil.test/worldstock/etf/SPY"},
        ]}
        self.assertIsNone(links.matching_url(payload, "SPY"))

    def test_class_share_search_variants_keep_class_identity(self):
        payloads = [
            {"items": []},
            {"items": [{"code": "BRK A", "nationCode": "USA",
                         "url": "/worldstock/stock/BRKa/total"}]},
            {"items": [{"code": "BRK B", "nationCode": "USA",
                         "url": "/worldstock/stock/BRKb/total"}]},
        ]
        with patch.object(links, "_search", side_effect=payloads) as search, \
             patch.object(links, "_verify_url", side_effect=lambda ticker, url: url):
            self.assertEqual(links.resolve_us_url("BRK-B"),
                             "https://m.stock.naver.com/worldstock/stock/BRKb/total")
        self.assertEqual([call.args[0] for call in search.call_args_list],
                         ["BRK-B", "BRK.B", "BRK B"])

    def test_failed_resolution_does_not_leave_partial_links(self):
        rows = [{"ticker": "VZ", "url": "old-vz"}, {"ticker": "MISSING", "url": "old-missing"}]
        def resolve(ticker):
            if ticker == "MISSING":
                raise RuntimeError("No exact match")
            return links.NAVER_ORIGIN + "/worldstock/stock/VZ/total"
        with patch.object(links, "resolve_us_url", side_effect=resolve):
            with self.assertRaisesRegex(RuntimeError, "MISSING"):
                links.resolve_us_links(rows)
        self.assertEqual([row["url"] for row in rows], ["old-vz", "old-missing"])

    def test_all_resolved_links_are_assigned_without_changing_order(self):
        rows = [{"ticker": "VZ"}, {"ticker": "NVDA"}, {"ticker": "TQQQ"}]
        urls = {ticker: links.NAVER_ORIGIN + path for ticker, path in (
            ("VZ", "/worldstock/stock/VZ/total"),
            ("NVDA", "/worldstock/stock/NVDA.O/total"),
            ("TQQQ", "/worldstock/etf/TQQQ.O"),
        )}
        with patch.object(links, "resolve_us_url", side_effect=urls.__getitem__):
            links.resolve_us_links(rows)
        self.assertEqual([row["ticker"] for row in rows], ["VZ", "NVDA", "TQQQ"])
        self.assertEqual([row["url"] for row in rows], list(urls.values()))

    def test_basic_identity_verification_checks_symbol_nation_route_and_url(self):
        payload = {"symbolCode": "NVDA", "reutersCode": "NVDA.O",
                   "stockEndType": "stock", "nationType": "USA",
                   "stockEndUrl": "https://m.stock.naver.com/worldstock/stock/NVDA.O"}
        url = payload["stockEndUrl"] + "/total"
        self.assertEqual(links.validate_basic(payload, "NVDA", url), url)
        for key, wrong in (("symbolCode", "NVDAA"), ("reutersCode", "NVDA"),
                           ("nationType", "KOR"), ("stockEndType", "etf"),
                           ("stockEndUrl", "https://m.stock.naver.com/worldstock/stock/NVDL.O")):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    links.validate_basic({**payload, key: wrong}, "NVDA", url)

    def test_basic_identity_accepts_etfs_and_class_shares(self):
        for ticker, symbol, code, route in (("TQQQ", "TQQQ", "TQQQ.O", "etf"),
                                            ("BRK-B", "BRK B", "BRKb", "stock")):
            url = f"https://m.stock.naver.com/worldstock/{route}/{code}"
            payload = {"symbolCode": symbol, "reutersCode": code,
                       "stockEndType": route, "stockExchangeType": {"nationCode": "USA"},
                       "endUrl": url}
            self.assertEqual(links.validate_basic(payload, ticker, url), url)

    def test_resolver_verifies_search_result_before_returning(self):
        payload = {"items": [{"code": "NVDA", "nationCode": "USA",
                             "url": "/worldstock/stock/NVDA.O/total"}]}
        with patch.object(links, "_search", return_value=payload), \
             patch.object(links, "_verify_url", side_effect=RuntimeError("identity mismatch")):
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                links.resolve_us_url("NVDA")

    def test_no_match_never_falls_back_to_guessed_bare_ticker_url(self):
        with patch.object(links, "_search", return_value={"items": []}):
            with self.assertRaisesRegex(RuntimeError, "no exact US security"):
                links.resolve_us_url("NOTLISTED")


class VerifiedNaverCloseTests(unittest.TestCase):
    url = "https://m.stock.naver.com/worldstock/etf/SOXX.O"
    basic_url = "https://api.stock.naver.com/stock/SOXX.O/basic"

    def basic(self, **changes):
        payload = {"symbolCode": "SOXX", "reutersCode": "SOXX.O", "stockEndType": "etf",
                   "nationType": "USA", "stockEndUrl": self.url,
                   "closePrice": "131.90", "localTradedAt": "2026-11-05T16:00:00-05:00"}
        return dict(payload, **changes)

    def test_latest_close_is_bound_to_the_verified_symbol_and_local_market_day(self):
        with patch.object(links, "_request_json", return_value=self.basic(closePrice="1,234.56")) as request:
            quote = links.verified_close("SOXX", self.url)
        self.assertEqual(quote, {"price": 1234.56, "date": "2026-11-05", "source_url": self.basic_url})
        request.assert_called_once_with(self.basic_url)

    def test_same_day_uses_basic_close_without_requesting_history(self):
        with patch.object(links, "_request_json", return_value=self.basic(closePriceRaw="132.125")) as request:
            quote = links.verified_close("SOXX", self.url + "/total", date(2026, 11, 5))
        self.assertEqual(quote["price"], 132.125)
        self.assertEqual(quote["date"], "2026-11-05")
        request.assert_called_once_with(self.basic_url)

    def test_detail_identity_mismatch_never_returns_the_other_security_price(self):
        for key, value in (("symbolCode", "SOXQ"), ("reutersCode", "SOXQ.O"),
                           ("nationType", "KOR"), ("stockEndType", "stock"),
                           ("stockEndUrl", "https://m.stock.naver.com/worldstock/etf/SOXQ.O")):
            with self.subTest(key=key), patch.object(links, "_request_json", return_value=self.basic(**{key: value})):
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    links.verified_close("SOXX", self.url, "2026-11-05")

    def test_untrusted_detail_urls_are_rejected_before_requesting_any_quote(self):
        for url in ("https://example.test/worldstock/etf/SOXX.O",
                    "https://m.stock.naver.com/worldstock/etf/SOXX.O?other=SOXQ",
                    "https://m.stock.naver.com/worldstock/etf/SOXX.O#other",
                    "https://m.stock.naver.com/domestic/stock/SOXX.O", None):
            with self.subTest(url=url), patch.object(links, "_request_json") as request:
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    links.verified_close("SOXX", url)
                request.assert_not_called()

    def test_invalid_dates_are_rejected_before_requesting_any_quote(self):
        for day in ("2026-11-35", "20261105", "2026-11-05T16:00:00", ""):
            with self.subTest(day=day), patch.object(links, "_request_json") as request:
                with self.assertRaises(ValueError):
                    links.verified_close("SOXX", self.url, day)
                request.assert_not_called()

    def test_latest_missing_or_nonpositive_quote_is_unavailable(self):
        for price in (None, 0, -1, "NaN", "inf", True, "--"):
            with self.subTest(price=price), patch.object(links, "_request_json", return_value=self.basic(closePrice=price)):
                self.assertIsNone(links.verified_close("SOXX", self.url))
        for traded_at in (None, "2026-02-30", "2026-11-05Tbad", "20261105"):
            with self.subTest(traded_at=traded_at), patch.object(links, "_request_json", return_value=self.basic(localTradedAt=traded_at)):
                self.assertIsNone(links.verified_close("SOXX", self.url))

    def test_requested_older_day_uses_only_the_exact_verified_daily_bar(self):
        params = {"startDateTime": "202611040000", "endDateTime": "202611042359"}
        chart_url = "https://api.stock.naver.com/chart/foreign/item/SOXX.O/day"
        # The provider revised this bar after the split. Neither version may be
        # changed by an assumed split factor inside the quote reader.
        for closing in (450.41, 150.1365):
            with self.subTest(provider_close=closing):
                chart = [{"localDate": "20261103", "closePrice": 464.82},
                         {"localDate": "20261104", "closePrice": closing}]
                responses = [Mock(json=Mock(return_value=value)) for value in (self.basic(), chart)]
                with patch.object(links.requests, "get", side_effect=responses) as request:
                    quote = links.verified_close("SOXX", self.url, "2026-11-04")
                self.assertEqual(request.call_args_list[1].args, (chart_url,))
                self.assertEqual(request.call_args_list[1].kwargs["params"], params)
                self.assertEqual(quote, {"price": closing, "date": "2026-11-04",
                                        "source_url": chart_url + "?startDateTime=202611040000&endDateTime=202611042359"})

    def test_missing_requested_bar_does_not_relabel_a_nearby_or_latest_quote(self):
        for chart in ({}, None, [],
                      [{"localDate": "20261103", "closePrice": 126.5}],
                      [{"localDate": "20261104", "closePrice": 0}],
                      [{"localDate": "20261135", "closePrice": 128.75}],
                      [{"localDate": "2026-11-04", "closePrice": 128.75}]):
            with self.subTest(chart=chart), patch.object(links, "_request_json", side_effect=[self.basic(), chart]):
                self.assertIsNone(links.verified_close("SOXX", self.url, "2026-11-04"))

    def test_conflicting_daily_bars_cannot_claim_one_verified_close(self):
        chart = [{"localDate": "20261104", "closePrice": 128.75},
                 {"localDate": "20261104", "closePrice": 129.75}]
        with patch.object(links, "_request_json", side_effect=[self.basic(), chart]):
            with self.assertRaisesRegex(RuntimeError, "quotes conflict"):
                links.verified_close("SOXX", self.url, "2026-11-04")


if __name__ == "__main__":
    unittest.main()
