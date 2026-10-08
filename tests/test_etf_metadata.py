import unittest
from unittest.mock import patch
from src.main import enrich_us_etf, parse_kr_etf_base
from src.email_layout import industry_text

class EtfMetadataTests(unittest.TestCase):
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
    def test_lookup_failure_keeps_explicit_name_based_fallback(self, ticker):
        ticker.side_effect = RuntimeError("unavailable")
        result = enrich_us_etf("TEST", "Example ETF", 1400)
        self.assertIn("명칭 기준", industry_text(dict(result, asset_type="ETF")))
        self.assertIsNone(result.get("aum"))

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

if __name__ == "__main__":
    unittest.main()
