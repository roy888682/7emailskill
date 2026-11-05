import unittest
from unittest.mock import patch

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

    def duplicated_listing(self):
        return {"items": [
            {"code": "HLT", "nationCode": "USA", "typeCode": "NASDAQ",
             "url": "/worldstock/stock/HLT.O/total"},
            {"code": "HLT", "nationCode": "USA", "typeCode": "NYSE",
             "url": "/worldstock/stock/HLT/total"},
        ]}

    def chart_identity(self, **overrides):
        meta = {"symbol": "HLT", "exchangeName": "NYQ", "instrumentType": "EQUITY"}
        meta.update(overrides)
        return {"chart": {"result": [{"meta": meta}], "error": None}}

    def test_ambiguous_symbol_requires_explicit_exchange_and_stays_order_independent(self):
        payload = self.duplicated_listing()
        for items in (payload["items"], list(reversed(payload["items"]))):
            with self.subTest(items=items):
                with self.assertRaises(links.AmbiguousNaverSymbol):
                    links.matching_url({"items": items}, "HLT")
                self.assertEqual(links.matching_url({"items": items}, "HLT", exchange="NYSE"),
                                 links.NAVER_ORIGIN + "/worldstock/stock/HLT/total")
                self.assertIsNone(links.matching_url({"items": items}, "HLT", exchange="UNKNOWN"))

    def test_ambiguous_listing_uses_yahoo_identity_then_rechecks_naver_exchange(self):
        basic = {"symbolCode": "HLT", "reutersCode": "HLT", "stockEndType": "stock",
                 "nationType": "USA", "stockExchangeName": "NYSE",
                 "stockExchangeType": {"name": "NYSE", "code": "NYS"},
                 "stockEndUrl": links.NAVER_ORIGIN + "/worldstock/stock/HLT"}
        def response(url, params=None):
            if url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/"):
                self.assertEqual(params, {"range": "5d", "interval": "1d"})
                return self.chart_identity()
            self.assertEqual(url, "https://api.stock.naver.com/stock/HLT/basic")
            return basic
        with patch.object(links, "_search", return_value=self.duplicated_listing()), \
             patch.object(links, "_request_json", side_effect=response) as request:
            self.assertEqual(links.resolve_us_url("HLT"), basic["stockEndUrl"] + "/total")
        self.assertEqual(request.call_count, 2)

    def test_ambiguous_listing_blocks_unverified_yahoo_symbol_type_or_exchange(self):
        for changed in ({"symbol": "HLTH"}, {"instrumentType": "INDEX"},
                        {"exchangeName": "UNKNOWN"}, {"exchangeName": None},
                        {"instrumentType": "ETF"}):
            links.resolve_us_url.cache_clear()
            with self.subTest(changed=changed), \
                 patch.object(links, "_search", return_value=self.duplicated_listing()), \
                 patch.object(links, "_request_json", return_value=self.chart_identity(**changed)), \
                 patch.object(links, "_verify_url") as verify:
                with self.assertRaises(RuntimeError):
                    links.resolve_us_url("HLT")
                verify.assert_not_called()

    def test_listing_lookup_failure_or_remaining_ambiguity_never_chooses_first_candidate(self):
        payload = self.duplicated_listing()
        payload["items"].append({"code": "HLT", "nationCode": "USA", "typeCode": "NYSE",
                                 "url": "/worldstock/stock/HLT.NEW/total"})
        for response in (self.chart_identity(), {"chart": {"result": [], "error": None}},
                         {"chart": {"result": [{"meta": {}}], "error": {"code": "Not Found"}}}):
            links.resolve_us_url.cache_clear()
            with self.subTest(response=response), \
                 patch.object(links, "_search", return_value=payload), \
                 patch.object(links, "_request_json", return_value=response), \
                 patch.object(links, "_verify_url") as verify:
                with self.assertRaises(RuntimeError):
                    links.resolve_us_url("HLT")
                verify.assert_not_called()
        with patch.object(links, "_search", return_value=payload), \
             patch.object(links, "_request_json", side_effect=RuntimeError("lookup unavailable")), \
             patch.object(links, "_verify_url") as verify:
            with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
                links.resolve_us_url("HLT")
            verify.assert_not_called()

    def test_basic_exchange_must_match_chart_evidence_and_not_conflict_in_detail(self):
        url = links.NAVER_ORIGIN + "/worldstock/stock/HLT/total"
        basic = {"symbolCode": "HLT", "reutersCode": "HLT", "stockEndType": "stock",
                 "nationType": "USA", "stockEndUrl": url.removesuffix("/total")}
        for venue in ({}, {"stockExchangeName": "NASDAQ"},
                      {"stockExchangeName": "NYSE", "stockExchangeType": {"name": "NASDAQ"}}):
            with self.subTest(venue=venue), self.assertRaisesRegex(RuntimeError, "exchange mismatch"):
                links.validate_basic({**basic, **venue}, "HLT", url, exchange="NYSE")


if __name__ == "__main__":
    unittest.main()
