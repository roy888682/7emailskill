import re
import unittest
from html.parser import HTMLParser
from src.email_layout import MAX_BODY_BYTES, etf_section_html, inception_text, render_email
from tools.preview_email import make_stock, sample_data

class EtfRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "etf-row" in attrs.get("class", "").split() and "data-ticker" in attrs:
            self.current = {"ticker": attrs["data-ticker"], "periods": []}
            self.cards.append(self.current)
        if self.current is not None and "data-period" in attrs:
            self.current["periods"].append(attrs["data-period"])

def rows_from(source):
    parser = EtfRows()
    parser.feed(source)
    return parser.cards

class EmailLayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()

    def test_representative_fixture_counts(self):
        self.assertEqual((len(self.data["us"]), len(self.data["kr"])), (213, 17))
        self.assertEqual((len(self.data["new_us"]), len(self.data["new_kr"])), (119, 1))
        self.assertEqual(len(self.data["etf_info"]["rows"]), 20)

    def test_rows_preserve_rank_and_all_five_periods(self):
        cards = rows_from(etf_section_html(self.data["etf_info"]))
        self.assertEqual([x["ticker"] for x in cards], [x["ticker"] for x in self.data["etf_info"]["rows"]])
        for card in cards:
            self.assertEqual(card["periods"], ["1y", "3y", "5y", "10y", "cumulative"])

    def test_etf_section_precedes_stock_lists(self):
        source = render_email(**self.data)
        self.assertLess(source.index('id="etf"'), source.index("US0000"))
        self.assertLess(source.index('id="etf"'), source.index("KR0000"))

    def test_countries_are_image_flags(self):
        source = render_email(**self.data)
        self.assertIn('src="cid:ath-flag-us"', source)
        self.assertIn('src="cid:ath-flag-kr"', source)
        self.assertFalse(any(0x1F1E6 <= ord(x) <= 0x1F1FF for x in source))

    def test_layout_avoids_scroll_tables_and_flex_grid(self):
        source = render_email(**self.data)
        self.assertNotRegex(source, r"display\s*:\s*(?:flex|grid)")
        self.assertNotRegex(source, r"overflow-x\s*:\s*(?:auto|scroll)")
        self.assertNotRegex(source, r"[{;]\s*min-width\s*:\s*[4-9]\d\dpx")

    def test_long_untrusted_metadata_is_escaped(self):
        row = self.data["etf_info"]["rows"][0]
        row.update({"name": '<script>alert("name")</script>' + "긴종목명" * 60,
                    "issuer": '<img onerror="alert(1)">', "etf_index": "<b>index</b>"})
        source = render_email(**self.data, include_all=True)
        self.assertNotIn("<script>", source)
        self.assertNotIn('<img onerror=', source)
        self.assertIn("&lt;script&gt;", source)
        self.assertIn("&lt;b&gt;index&lt;/b&gt;", source)

    def test_body_budget_preserves_etfs_and_complete_attachment(self):
        self.assertLessEqual(MAX_BODY_BYTES, 85000)
        self.data["us"] = [make_stock("US%04d" % i, number=i) for i in range(500)]
        self.data["kr"] = [make_stock("KR%04d" % i, market="KOSPI", number=i) for i in range(500)]
        body = render_email(**self.data)
        self.assertLessEqual(len(body.encode("utf-8")), MAX_BODY_BYTES)
        self.assertIn("전체 목록은 첨부 리포트", body)
        self.assertEqual(len(rows_from(body)), 20)
        complete = render_email(**self.data, include_all=True)
        for stock in self.data["us"] + self.data["kr"]:
            self.assertIn(stock["ticker"], complete)

    def test_comparison_uses_shared_unit_and_details_stay_in_attachment(self):
        body = render_email(**self.data)
        complete = render_email(**self.data, include_all=True)
        self.assertIn("단위: %", body)
        self.assertIn("최근 1·3·5·10년: 연평균수익률(CAGR)", body)
        self.assertNotIn('<div class="etf-details">', body)
        self.assertIn('<div class="etf-details">', complete)
        self.assertIn("신한자산운용 주식회사", complete)

    def test_inception_date_uses_disclosed_date_and_history_fallback(self):
        self.assertEqual(inception_text({"inception": "2018-04-05", "first_date": "2016-01-02"}), "2018-04-05")
        self.assertEqual(inception_text({"first_date": "2016-01-02"}), "2016-01-02")
        self.assertEqual(inception_text({"inception": "20230425"}), "2023-04-25")
        self.assertEqual(inception_text({}), "-")
        row = dict(self.data["etf_info"]["rows"][0], inception="2018-04-05")
        source = etf_section_html({"rows": [row]})
        self.assertRegex(source, r'data-period="cumulative"[\s\S]*?</td><td class="date-cell" data-field="inception">2018-04-05</td>')
        self.assertIn('<th data-field="inception">설립일</th>', source)

    def test_empty_report_is_valid(self):
        source = render_email([], [], self.data["info"], 1343.4)
        self.assertLessEqual(len(source.encode("utf-8")), MAX_BODY_BYTES)
        self.assertIn("해당 ETF 없음", source)
        self.assertEqual(rows_from(source), [])
        self.assertNotIn("None", source)

if __name__ == "__main__":
    unittest.main()
