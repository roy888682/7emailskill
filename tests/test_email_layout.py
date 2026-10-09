"""Regressions for the restored 38-security desktop table and direct delivery."""
import unittest
from bs4 import BeautifulSoup
from src.email_layout import (render_email, etf_section_html, inception_text,
                              row_size, industry_text, inventory, validate_size,
                              validate_inventory, MAX_EMAIL_BYTES, CSS, compact_transport_html)
from tools.preview_email import sample_data, make_stock

class EmailLayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.data["new_us"] = self.data["new_us"][:10]
        self.data["new_kr"] = []
        self.data["us"].extend(make_stock(f"EXTRA{i}", number=i) for i in range(5))
    def test_includes_all_218_us_and_17_kr_rows(self):
        body = render_email(**self.data)
        actual = inventory(body)
        expected = {"us":[row["ticker"] for row in self.data["us"]],
                    "kr":[row["ticker"] for row in self.data["kr"]],
                    "new":["US:"+row["ticker"] for row in self.data["new_us"]],
                    "etf":[row["ticker"] for row in self.data["etf_info"]["rows"]]}
        self.assertEqual(validate_inventory(body, expected), expected)
        self.assertEqual((len(actual["us"]),len(actual["kr"])),(218,17))
        doc = BeautifulSoup(body, "html5lib")
        self.assertEqual([node.get_text() for node in doc.select(".count")], ["17 종목","218 종목"])
    def test_restores_original_header_alignment(self):
        body = render_email(**self.data)
        self.assertIn("text-align:left", body)
        self.assertIn("text-align:right;font-variant-numeric:tabular-nums", body)
        self.assertNotIn(".tbl", body)
        doc = BeautifulSoup(body, "html5lib")
        self.assertNotIn("n",doc.select("#us th")[3].get("class",[]))
    def test_new_list_is_complete_and_precedes_etf(self):
        body = render_email(**self.data)
        self.assertEqual(inventory(body)["new"],["US:"+row["ticker"] for row in self.data["new_us"]])
        self.assertLess(body.index('id=new-stocks'),body.index('id=etf'))
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
        self.assertTrue(doc.select(".stock-table i, .new-table i"))
        self.assertTrue(doc.select(".stock-table b, .new-table b"))
        for row in doc.select("#us tbody tr, #kr tbody tr, #new tbody tr"):
            cells=row.find_all("td",recursive=False)
            self.assertIn("r",cells[6].get("class",[]))
            self.assertIn("r",cells[8].get("class",[]))
    def test_every_security_table_has_sequential_no_column(self):
        body = render_email(**self.data)
        doc = BeautifulSoup(body, "html5lib")
        for table_id, count, columns in (("us",218,11),("kr",17,11),("new",10,10),("returns",20,11)):
            table = doc.find("table", id=table_id)
            self.assertEqual(table.select_one("thead th").get_text(strip=True), "No.")
            rows = table.select("tbody tr")
            self.assertEqual(len(rows), count)
            self.assertEqual([row.find_all("td",recursive=False)[0].get_text(strip=True) for row in rows],
                             [str(number) for number in range(1,count+1)])
            self.assertTrue(all(len(row.find_all("td",recursive=False)) == columns for row in rows))

    def test_mixed_new_list_numbers_continue_across_countries(self):
        body = render_email(**dict(self.data, new_kr=self.data["kr"][:2], new_us=self.data["us"][:3]))
        doc = BeautifulSoup(body, "html5lib")
        rows = doc.select("#new tbody tr")
        self.assertEqual([row.find_all("td",recursive=False)[0].get_text(strip=True) for row in rows],
                         ["1","2","3","4","5"])
        self.assertEqual(inventory(body)["new"],
                         ["KR:"+row["ticker"] for row in self.data["kr"][:2]] +
                         ["US:"+row["ticker"] for row in self.data["us"][:3]])

    def test_optional_etf_details_also_include_sequential_numbers(self):
        doc = BeautifulSoup(etf_section_html(self.data["etf_info"], include_details=True), "html5lib")
        table = doc.select_one(".etf-details table")
        self.assertEqual(table.select_one("thead th").get_text(strip=True), "No.")
        self.assertEqual([row.find_all("td",recursive=False)[0].get_text(strip=True) for row in table.select("tbody tr")],
                         [str(number) for number in range(1,21)])

    def test_transport_compaction_preserves_the_exact_table_dom(self):
        from unittest.mock import patch
        with patch("src.email_layout.compact_transport_html", side_effect=lambda source: source):
            expanded = render_email(**self.data)
        compact = compact_transport_html(expanded)
        before, after = (BeautifulSoup(source, "html5lib") for source in (expanded, compact))
        for table_id in ("us","kr","new","returns"):
            def cells(document):
                return [(cell.get_text(),[a.get("href") for a in cell.select("a")],
                         [img.get("src") for img in cell.select("img")])
                        for cell in document.find("table",id=table_id).select("th,td")]
            self.assertEqual(cells(before),cells(after))
        self.assertLess(len(compact.encode("utf-8")),len(expanded.encode("utf-8")))
        self.assertEqual(inventory(compact),inventory(expanded))

    def test_layout_styles_are_identical_to_the_accepted_version(self):
        self.assertEqual(CSS, BASELINE_CSS)

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
        self.assertLessEqual(MAX_EMAIL_BYTES,85000)
        with self.assertRaises(RuntimeError):
            validate_size("가"*30000)
    def test_existing_drawn_flags_and_fonts_are_preserved(self):
        body=render_email(**self.data)
        self.assertIn('src=cid:u',body)
        self.assertIn('src=cid:k',body)
        self.assertNotRegex(body,r"display\s*:\s*(?:flex|grid)")
        self.assertRegex(body,r"\.shell\{[^}]*font-size:12px")
        self.assertNotIn("data-key=",body)
        self.assertNotIn("data-period=",body)

BASELINE_CSS = "\nbody{margin:0;background:#f2f5f8;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.4}\ntable{border-collapse:collapse}a{color:#1260ad;text-decoration:none}\n.shell{max-width:1360px;margin:0 auto;padding:12px;color:#17263d;background:#f2f5f8;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.4}.layout{width:100%;table-layout:fixed}\n.hero{background:#11243c;color:#fff;border-radius:9px;padding:12px 16px}.hero .eyebrow{display:none}\n.hero h1{font-size:19px;line-height:1.2;margin:0 0 5px}.date{font-size:11px;color:#c5d5e4}\n.hero .foot{font-size:10px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:6px;margin-top:7px}\n.summary{margin-top:8px;background:#fff;border:1px solid #dfe7ef;border-radius:8px;padding:8px 10px}\n.summary td{width:50%;padding:0 6px;vertical-align:top}.count{font-size:17px;font-weight:bold}\n.market{font-weight:bold;font-size:11px;margin-bottom:2px}.muted{font-size:10px;color:#667a90}\n.section{margin-top:14px}.section h2{margin:0;font-size:16px;line-height:1.25}\n.intro,.etf-caption{font-size:10px;color:#64778b;margin:4px 0 7px}\n.data-table{width:100%;table-layout:auto;background:#fff;border:1px solid #dce5ee;font-size:9.5px;line-height:1.25}\n.data-table th,.data-table td{white-space:nowrap;padding:3px 3px;text-align:left;vertical-align:middle}\n.data-table th{background:#163b68;color:#fff;font-weight:bold;font-size:10px}\n.stock-table th{background:#ee990b;color:#fff}\n.asset{display:inline-block;border-radius:3px;padding:1px 4px;font-size:9px;font-weight:bold}.s{background:#dff3ee;color:#087569}.e{background:#eee5fa;color:#753caf}\n.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}\n.data-table .n{text-align:right;font-variant-numeric:tabular-nums}\n.data-table .f{text-align:center;padding-left:3px;padding-right:3px}.f img{width:20px;height:auto;vertical-align:middle}\n.data-table .t{font-weight:bold}.data-table .y{background:#eaf1fb;font-weight:bold}\n.data-table th.y{background:#2b4665;color:#fff}.data-table .d{font-size:9.5px}\n.etf-comparison .data-table{font-size:10px}.metric-label{display:none}.m{display:block;font-size:10px;font-weight:bold;line-height:1.25}\n.etf-details{margin-top:12px}.etf-details h3{font-size:13px;margin:0 0 6px}\n.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}\n.new-section{border-top:3px solid #ee990b;padding-top:8px}.new-table th{background:#ee990b}.r{color:#c23932}.data-table .p1{color:#c23932}.data-table .p3{color:#245ba6}.data-table .p5{color:#087d67}.data-table .p10{color:#7944b0}.data-table .z{background:#f6f8fb}\n.new{background:#e6f3ed;color:#237353;border-radius:3px;padding:0 3px;margin-left:3px;font-size:8px;font-weight:bold}\n.notice{background:#fff4dc;color:#796438;border-radius:6px;padding:8px 10px;font-size:10px;margin:8px 0}\n.report-note{padding:8px 10px;background:#e8f0f8;border-radius:6px;color:#405d7a;font-size:10px}\n.notes{font-size:9px;line-height:1.5;color:#75869a;margin:8px 0}.footer{text-align:center;color:#8a9aab;font-size:9px;padding:16px 0 8px}\n"

if __name__=="__main__":
    unittest.main()
