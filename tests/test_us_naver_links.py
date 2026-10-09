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


if __name__ == "__main__":
    unittest.main()
