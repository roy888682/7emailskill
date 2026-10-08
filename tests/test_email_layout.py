import re
import unittest
from html.parser import HTMLParser
from src.email_layout import etf_section_html, inception_text, render_email, row_size, industry_text, inventory
from bs4 import BeautifulSoup
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
    doc = BeautifulSoup(source, "html5lib")
    table = doc.find("table", id="returns")
    if table:
        return [{"ticker": str(row.find_all("td")[2].find("a").contents[0]),
                 "periods": ["1y", "3y", "5y", "10y", "cumulative"]}
                for row in table.select("tbody tr")]
    parser = EtfRows()
    parser.feed(source)
    return parser.cards

class EmailLayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.data["new_us"] = self.data["new_us"][:10]

    def test_representative_fixture_counts(self):
        self.assertEqual((len(self.data["us"]), len(self.data["kr"])), (213, 17))
        fixture = sample_data()
        self.assertEqual((len(fixture["new_us"]), len(fixture["new_kr"])), (119, 1))
        self.assertEqual(len(self.data["etf_info"]["rows"]), 20)

    def test_rows_preserve_rank_and_all_five_periods(self):
        cards = rows_from(etf_section_html(self.data["etf_info"]))
        self.assertEqual([x["ticker"] for x in cards], [x["ticker"] for x in self.data["etf_info"]["rows"]])
        for card in cards:
            self.assertEqual(card["periods"], ["1y", "3y", "5y", "10y", "cumulative"])

    def test_etf_section_precedes_stock_lists(self):
        source = render_email(**self.data)
        self.assertLess(source.index('id="etf"'), source.index('id="kr"'))
        self.assertLess(source.index('id="etf"'), source.index('id="kr"'))

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
        source = render_email(**self.data)
        self.assertNotIn("<script>", source)
        self.assertNotIn('<img onerror=', source)
        self.assertIn("&lt;script&gt;", source)
        self.assertIn("&lt;b&gt;index&lt;/b&gt;", source)

    def test_all_candidates_are_in_body_even_above_previous_85kb_limit(self):
        self.data["us"] = [make_stock(f"US{i:04d}", number=i) for i in range(500)]
        self.data["kr"] = [make_stock(f"KR{i:04d}", market="KOSPI", number=i) for i in range(500)]
        body = render_email(**self.data)
        self.assertGreater(len(body.encode("utf-8")), 85000)
        expected = ["KR:" + r["ticker"] for r in self.data["kr"]] + ["US:" + r["ticker"] for r in self.data["us"]]
        keys = ["KR:" + x for x in inventory(body)["kr"]] + ["US:" + x for x in inventory(body)["us"]]
        self.assertEqual(keys, expected)
        self.assertEqual(len(rows_from(body)), 20)
        self.assertNotIn("첨부", body)
        self.assertEqual(len(inventory(body)["us"]), 500)
        self.assertEqual(len(inventory(body)["kr"]), 500)

    def test_etf_details_and_shared_units_are_in_body(self):
        body = render_email(**self.data)
        self.assertIn("단위: %", body)
        self.assertIn("최근 1·3·5·10년: 연평균수익률(CAGR)", body)
        self.assertIn('<div class=etf-details>', body)
        self.assertIn("신한자산운용 주식회사", body)
        self.assertNotIn("첨부", body)

    def test_inception_date_uses_disclosed_date_and_history_fallback(self):
        self.assertEqual(inception_text({"inception": "2018-04-05", "first_date": "2016-01-02"}), "2018-04-05")
        self.assertEqual(inception_text({"first_date": "2016-01-02"}), "2016-01-02")
        self.assertEqual(inception_text({"inception": "20230425"}), "2023-04-25")
        self.assertEqual(inception_text({}), "-")
        row = dict(self.data["etf_info"]["rows"][0], inception="2018-04-05")
        source = etf_section_html({"rows": [row]})
        self.assertRegex(source, r'data-period="cumulative"[\s\S]*?</td><td class="number" data-field="aum">[^<]+</td><td class="date-cell" data-field="inception">2018-04-05</td>')
        self.assertIn('<th data-field="inception">설립일</th>', source)

    def test_new_list_is_visible_before_etf_and_contains_every_new_security(self):
        source = render_email(**self.data)
        self.assertLess(source.index('id="new-stocks"'), source.index('id="etf"'))
        keys = inventory(source)["new"]
        expected = ["KR:" + r["ticker"] for r in self.data["new_kr"]] + ["US:" + r["ticker"] for r in self.data["new_us"]]
        self.assertEqual(keys, expected)

    def test_large_new_lists_and_regular_lists_remain_in_single_body(self):
        for count in (119, 500):
            with self.subTest(count=count):
                data = sample_data()
                data["us"] = [make_stock(f"NEW{i:04d}", number=i) for i in range(count)]
                data["new_us"] = data["us"]
                body = render_email(**data)
                new_keys = inventory(body)["new"]
                stock_keys = inventory(body)["us"] + inventory(body)["kr"]
                expected = ["KR:" + r["ticker"] for r in data["new_kr"]] + ["US:" + r["ticker"] for r in data["new_us"]]
                self.assertEqual(new_keys, expected)
                self.assertEqual(len(stock_keys), len(data["kr"]) + count)
                self.assertEqual(len(rows_from(body)), 20)
                self.assertNotIn("첨부", body)

    def test_requested_colors_size_preference_and_no_current_price(self):
        source = render_email(**self.data)
        self.assertNotIn("현재가", source)
        for period, cls, color in (("1y", "p1", "#c23932"), ("3y", "p3", "#245ba6"),
                                   ("5y", "p5", "#087d67"), ("10y", "p10", "#7944b0")):
            self.assertIn(color, source)
            self.assertIn("class=" + cls, source)
        self.assertIn('class=e', source)
        self.assertIn('class=s', source)
        for value in (-9.9, 0, 2.5):
            row = make_stock("COLOR")
            row.update(gap=value, change=value)
            html = render_email([row], [], self.data["info"], 1400)
            self.assertEqual(html.count('class=r'), 2)
        self.assertEqual(row_size({"asset_type": "ETF", "aum": 1.4, "mcap": 9}), "1.40조원")
        self.assertEqual(row_size({"asset_type": "ETF", "aum": None, "mcap": .0034}), "34억원")
        self.assertEqual(row_size({"asset_type": "주식", "aum": 9, "mcap": 1.2}), "1.20조원")
        self.assertEqual(industry_text({"asset_type": "ETF", "investment_area": "반도체"}), "반도체")
        self.assertIn("명칭 기준", industry_text({"asset_type": "ETF", "etf_kind": "반도체"}))
        self.assertEqual(industry_text({"asset_type": "주식"}), "미확인")

    def test_compaction_preserves_every_cell_with_html5_optional_end_tags(self):
        from src.email_layout import compact_html, validate_inventory
        body = render_email(**self.data)
        expected = {"us":[x["ticker"] for x in self.data["us"]],
                    "kr":[x["ticker"] for x in self.data["kr"]],
                    "new":["KR:"+x["ticker"] for x in self.data["new_kr"]] + ["US:"+x["ticker"] for x in self.data["new_us"]],
                    "etf":[x["ticker"] for x in self.data["etf_info"]["rows"]]}
        self.assertEqual(validate_inventory(body, expected), expected)
        self.assertNotIn("data-key", body)
        self.assertNotIn("data-period", body)
        doc = BeautifulSoup(body, "html5lib")
        for table_id, columns in (("us",10),("kr",10),("new",9),("returns",11)):
            for row in doc.select("#" + table_id + " tbody tr"):
                self.assertEqual(len(row.find_all("td", recursive=False)), columns)
        row = doc.select_one("#returns tbody tr").find_all("td", recursive=False)
        self.assertEqual([cell.get_text() for cell in row[4:9]],
                         [f'{self.data["etf_info"]["rows"][0][key]:.1f}' if self.data["etf_info"]["rows"][0].get(key) is not None else "-"
                          for key in ("cagr1y","cagr3y","cagr5y","cagr10y","cumulative_return")])
        self.assertRegex(body, r"\.shell\{[^}]*font-size:12px")
        self.assertLess(len(body.encode("utf-8")), 140000)

    def test_empty_report_is_valid(self):
        source = render_email([], [], self.data["info"], 1343.4)
        self.assertIn("해당 ETF 없음", source)
        self.assertEqual(rows_from(source), [])
        self.assertNotIn("None", source)

if __name__ == "__main__":
    unittest.main()
