import unittest
from unittest.mock import patch
from src.main import enrich_us_etf, parse_kr_etf_base
from src.email_layout import industry_text
from src.etf_strategy import management_style_metadata, management_style_error, STYLE_FIELDS

class EtfMetadataTests(unittest.TestCase):
    @patch("src.main.yf.Ticker")
    def test_official_management_style_overrides_vendor_benchmark_wording(self, ticker):
        ticker.return_value.info = {"longBusinessSummary": "The fund tracks the S&P 500 Index."}
        for symbol in ("MAGS", "DFAC", "JEPI", "JEPQ", "AVUV"):
            result = enrich_us_etf(symbol, symbol, 1400)
            self.assertEqual(result["management_style"], "Active")
            self.assertTrue(result["management_style_verified"])
            self.assertIsNone(management_style_error(dict(result, ticker=symbol, market="US")))

    @patch("src.main.yf.Ticker")
    def test_us_assets_apply_fx_once_and_prefer_sector(self, ticker):
        ticker.return_value.info = {
            "sector": "Technology", "category": "Large Growth", "totalAssets": 2_000_000_000,
            "fundFamily": "Example", "fundInceptionDate": 1577836800}
        result = enrich_us_etf("TEST", "Example ETF", 1400)
        ticker.assert_called_once_with("TEST")
        self.assertEqual(result["aum"], 2.8)
        self.assertEqual(result["investment_area"], "기술")
        self.assertIn("Yahoo", result["investment_area_source"])
        self.assertEqual(result["inception"], "2020-01-01")

    @patch("src.main.yf.Ticker")
    def test_us_category_when_sector_missing(self, ticker):
        ticker.return_value.info = {"category": "Large Growth"}
        self.assertEqual(enrich_us_etf("TEST", "Example ETF", 1400)["investment_area"], "미국 대형 성장")

    @patch("src.main.yf.Ticker")
    def test_gbtc_keeps_trust_and_public_quote_dates_separate_from_etf_listing(self, ticker):
        ticker.return_value.info = {"fundInceptionDate": 1380067200}
        result = enrich_us_etf("GBTC", "Grayscale Bitcoin Trust ETF", 1400)
        self.assertEqual(result["inception"], "2024-01-11")
        self.assertEqual(result["inception_label"], "ETF 전환·상장일")
        self.assertTrue(result["inception_verified"])
        self.assertEqual(result["trust_inception"], "2013-09-25")
        self.assertEqual(result["public_quotation_date"], "2015-05-04")
        self.assertEqual(result["etf_listing_date"], "2024-01-11")
        self.assertEqual(result["inception_url"], "https://etfs.grayscale.com/gbtc")
        self.assertNotIn("predecessor_inception", result)

    @patch("src.main.yf.Ticker")
    def test_lookup_failure_keeps_explicit_name_based_fallback(self, ticker):
        ticker.side_effect = RuntimeError("unavailable")
        result = enrich_us_etf("TEST", "Example ETF", 1400)
        self.assertIn("명칭 기준", industry_text(dict(result, asset_type="ETF")))
        self.assertIsNone(result.get("aum"))
        self.assertEqual(set(STYLE_FIELDS) - set(result), set())
        self.assertEqual(result["management_style"], "미확인")
        self.assertIsNone(result["management_style_url"])
        self.assertIsNone(result["management_style_evidence"])
        self.assertIsNone(management_style_error(result))

    def test_confirmed_kr_fields_use_won_units(self):
        result = parse_kr_etf_base({"etfBaseIdx": "KOSPI 200", "etfType": "국내주식형, 대표지수",
            "issueName": "삼성자산운용", "listedDate": "20021014",
            "totalNetAssets": "1,250,000,000,000", "marketSum": "98765"})
        self.assertEqual(result["etf_index"], "KOSPI 200")
        self.assertEqual(result["issuer"], "삼성자산운용")
        self.assertEqual(result["inception"], "2002-10-14")
        self.assertEqual(result["aum"], 1.25)
        self.assertEqual(result["investment_area"], "국내주식형, 대표지수")
        self.assertIn("Naver", result["investment_area_source"])

    def test_small_assets_never_guess_units(self):
        self.assertAlmostEqual(parse_kr_etf_base({"totalNetAssets": "99,000,000"})["aum"], .000099, places=4)

    def test_missing_invalid_metadata_does_not_invent_values(self):
        for data in (None, {}, {"listedDate": "not-a-date", "totalNetAssets": "unavailable"},
                     {"totalNetAssets": "-100"}, {"totalNetAssets": "NaN"}):
            with self.subTest(data=data):
                result = parse_kr_etf_base(data)
                self.assertIsNone(result["aum"])
                self.assertIsNone(result["inception"])
                self.assertIsNone(result["investment_area"])


class ManagementStyleEvidenceTests(unittest.TestCase):
    def vendor(self, summary, **extra):
        return management_style_metadata({"ticker": "EXAMPLE", "market": "US", **extra},
                                         {"longBusinessSummary": summary})

    def test_explicit_active_policy_wins_over_benchmark_index_mentions(self):
        result = self.vendor("The fund is actively managed. Its benchmark is the S&P 500 Index.")
        self.assertEqual(result["management_style"], "Active")
        self.assertFalse(result["management_style_verified"])
        self.assertIn("Yahoo", result["management_style_source"])

    def test_explicit_index_tracking_is_passive_including_daily_leverage(self):
        for summary in ("The fund seeks to track the performance of the Example Index.",
                        "The fund seeks daily returns corresponding to three times the Example Index.",
                        "The fund uses an indexing investment approach.",
                        "This fund is not actively managed."):
            with self.subTest(summary=summary):
                result = self.vendor(summary)
                self.assertEqual(result["management_style"], "Passive")
                self.assertFalse(result["management_style_verified"])

    def test_absent_active_name_or_a_comparison_index_never_implies_passive(self):
        for summary in ("", "The fund has a benchmark called the Example Index.",
                        "The fund seeks to outperform the S&P 500 Index.",
                        "The fund does not seek to track an Index.",
                        "The fund is not passively managed."):
            with self.subTest(summary=summary):
                result = self.vendor(summary, name="Triple Leveraged Index ETF", etf_index="Example Index")
                self.assertEqual(result["management_style"], "미확인")
                self.assertIsNone(result["management_style_url"])

    def test_checked_leveraged_issuer_policy_is_passive_not_active_by_leverage(self):
        for symbol in ("TQQQ", "SPXL", "UPRO"):
            row = {"ticker": symbol, "market": "US", "name": "Daily 3X ETF"}
            result = management_style_metadata(row)
            self.assertEqual(result["management_style"], "Passive")
            self.assertTrue(result["management_style_verified"])
            self.assertIsNone(management_style_error(dict(row, **result)))

    def test_korean_checked_issuer_policy_uses_the_korean_identity(self):
        row = {"ticker": "449180", "market": "KOSPI", "name": "KODEX 미국S&P500(H)"}
        result = management_style_metadata(row)
        self.assertEqual(result["management_style"], "Passive")
        self.assertTrue(result["management_style_verified"])
        self.assertIn("samsungfund.com", result["management_style_url"])
        self.assertIsNone(management_style_error(dict(row, **result)))

    def test_korean_active_name_is_explicit_unverified_provider_evidence(self):
        row = {"ticker": "123456", "market": "KOSPI", "name": "TIGER 예시액티브"}
        result = management_style_metadata(row)
        self.assertEqual(result["management_style"], "Active")
        self.assertFalse(result["management_style_verified"])
        self.assertIn("종목명", result["management_style_source"])
        self.assertEqual(management_style_metadata(dict(row, name="TIGER 예시지수"))["management_style"], "미확인")

    def test_complete_recorded_vendor_evidence_is_preserved_without_mutation(self):
        row = {"ticker": "TEST", "market": "US", **self.vendor("The fund is actively managed.")}
        before = dict(row)
        self.assertEqual(management_style_metadata(row), {key: row[key] for key in STYLE_FIELDS})
        self.assertEqual(row, before)
        self.assertIsNone(management_style_error(row))

    def test_false_official_claim_incomplete_or_unknown_claims_are_rejected(self):
        result = self.vendor("The fund is actively managed.")
        for change in ({"management_style_verified": True}, {"management_style_url": None},
                       {"management_style_source": ""}, {"management_style_evidence": None},
                       {"management_style": "미확인"}, {"management_style": "Index"}):
            with self.subTest(change=change):
                row = {"ticker": "TEST", "market": "US", **result, **change}
                self.assertIsNotNone(management_style_error(row))
                with self.assertRaises(ValueError):
                    management_style_metadata(row)
        partial = {"ticker": "TEST", "market": "US", "management_style": "Active"}
        with self.assertRaises(ValueError):
            management_style_metadata(partial)

if __name__ == "__main__":
    unittest.main()
