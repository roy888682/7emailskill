"""Regressions for the restored 38-security desktop table and direct delivery."""
import unittest
from bs4 import BeautifulSoup
from src.email_layout import (render_email, etf_section_html, inception_text,
                              row_size, industry_text, inventory, validate_size,
                              validate_inventory, US_VISIBLE_LIMIT, MAX_EMAIL_BYTES)
from tools.preview_email import sample_data, make_stock

class EmailLayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.data["new_us"] = self.data["new_us"][:10]
        self.data["new_kr"] = []
    def test_restores_exact_first_38_us_rows_and_all_17_kr_rows(self):
        body = render_email(**self.data)
        actual = inventory(body)
        expected = {"us":[row["ticker"] for row in self.data["us"][:38]],
                    "kr":[row["ticker"] for row in self.data["kr"]],
                    "new":["US:"+row["ticker"] for row in self.data["new_us"]],
                    "etf":[row["ticker"] for row in self.data["etf_info"]["rows"]]}
        self.assertEqual(validate_inventory(body, expected), expected)
        self.assertEqual((len(actual["us"]),len(actual["kr"])),(38,17))
        self.assertEqual(US_VISIBLE_LIMIT,38)
        doc = BeautifulSoup(body, "html5lib")
        self.assertEqual([node.get_text() for node in doc.select(".count")], ["17 종목","38 종목"])
    def test_restores_original_header_alignment(self):
        body = render_email(**self.data)
        self.assertIn("text-align:left", body)
        self.assertIn(".data-table .n{text-align:right", body)
        self.assertNotIn(".tbl", body)
        doc = BeautifulSoup(body, "html5lib")
        self.assertNotIn("n",doc.select("#us th")[2].get("class",[]))
    def test_new_list_is_complete_and_precedes_etf(self):
        body = render_email(**self.data)
        self.assertEqual(inventory(body)["new"],["US:"+row["ticker"] for row in self.data["new_us"]])
        self.assertLess(body.index('id="new-stocks"'),body.index('id="etf"'))
        self.assertNotIn("현재가",body)
    def test_no_report_attachment_copy_or_expansion_links(self):
        body = render_email(**self.data)
        for text in ("첨부","전체 메일 보기","전체 메시지 보기","mail.google.com","view=lg"):
            self.assertNotIn(text,body)
        doc = BeautifulSoup(body,"html5lib")
        self.assertIsNone(doc.select_one(".etf-details"))
        self.assertIsNone(doc.select_one(".report-note"))
    def test_all_return_columns_and_aum_inception_remain(self):
        body = render_email(**self.data)
        doc = BeautifulSoup(body, "html5lib")
        rows = doc.select("#returns tbody tr")
        self.assertEqual(len(rows),20)
        for item,row in zip(self.data["etf_info"]["rows"],rows):
            cells=row.find_all("td",recursive=False)
            self.assertEqual(len(cells),11)
            for index,key in enumerate(("cagr1y","cagr3y","cagr5y","cagr10y","cumulative_return"),4):
                value=item.get(key)
                self.assertEqual(cells[index].get_text(),f"{value:.1f}" if value is not None else "-")
            self.assertEqual(cells[9].get_text(),row_size(dict(item,asset_type="ETF")))
            self.assertEqual(cells[10].get_text(),inception_text(item))
            self.assertEqual([cells[i].get("class",[])[-1] for i in range(4,8)],["p1","p3","p5","p10"])
    def test_signed_values_and_different_asset_badges_are_preserved(self):
        body = render_email(**self.data)
        doc=BeautifulSoup(body,"html5lib")
        self.assertTrue(doc.select("b.e"))
        self.assertTrue(doc.select("b.s"))
        for row in doc.select("#us tbody tr, #kr tbody tr, #new tbody tr"):
            cells=row.find_all("td",recursive=False)
            self.assertIn("r",cells[5].get("class",[]))
            self.assertIn("r",cells[7].get("class",[]))
    def test_missing_data_and_empty_report(self):
        self.assertEqual(inception_text({"first_date":"2016-01-02"}),"2016-01-02")
        self.assertEqual(inception_text({"inception":"20230425"}),"2023-04-25")
        self.assertEqual(row_size({"asset_type":"ETF","aum":1.4,"mcap":9}),"1.40조원")
        self.assertEqual(row_size({"asset_type":"ETF","aum":None,"mcap":.0034}),"34억원")
        self.assertEqual(industry_text({"asset_type":"ETF","investment_area":"반도체"}),"반도체")
        body=render_email([],[],self.data["info"],1342)
        self.assertEqual(inventory(body),{"us":[],"kr":[],"new":[],"etf":[]})
        self.assertIn("해당 ETF 없음",body)
    def test_long_untrusted_text_is_escaped(self):
        row = self.data["etf_info"]["rows"][0]
        row["name"]='<script>alert("name")</script>'
        body=render_email(**self.data)
        self.assertNotIn("<script>",body)
        self.assertIn("&lt;script&gt;",body)
    def test_stricter_delivery_size_guard(self):
        self.assertLessEqual(MAX_EMAIL_BYTES,65000)
        with self.assertRaises(RuntimeError):
            validate_size("가"*30000)
    def test_existing_drawn_flags_and_fonts_are_preserved(self):
        body=render_email(**self.data)
        self.assertIn('src="cid:ath-flag-us"',body)
        self.assertIn('src="cid:ath-flag-kr"',body)
        self.assertNotRegex(body,r"display\s*:\s*(?:flex|grid)")
        self.assertRegex(body,r"\.shell\{[^}]*font-size:12px")
        self.assertNotIn("data-key=",body)
        self.assertNotIn("data-period=",body)

if __name__=="__main__":
    unittest.main()
