"""Regressions for the restored 38-security desktop table and direct delivery."""
import unittest
from bs4 import BeautifulSoup
from src.email_layout import (render_email, etf_section_html, inception_text,
                              row_size, row_size_html, aum, industry_text, inventory, validate_size,
                              validate_inventory, MAX_EMAIL_BYTES, CSS, compact_transport_html, security_count,
                              elapsed_years_text)
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
        self.assertEqual([node.get_text() for node in doc.select(".count")], ["17종목","218종목"])

    def test_country_and_new_counts_show_independent_stock_etf_breakdowns(self):
        us = [make_stock("US%04d" % i, number=i, asset_type="주식" if i < 75 else "ETF") for i in range(229)]
        kr = [make_stock("KR%04d" % i, market="KOSPI", number=i, asset_type="주식" if i < 4 else "ETF") for i in range(11)]
        new_us, new_kr = us[:5] + us[75:99], kr[:1] + kr[4:7]
        data = dict(self.data, us=us, kr=kr, new_us=new_us, new_kr=new_kr)
        doc = BeautifulSoup(render_email(**data), "html5lib")
        markets = [node.get_text() for node in doc.select(".summary .market")]
        self.assertEqual(markets, ["한국 11종목( 4종목 주식, 7종목 ETF )",
                                   "미국 229종목( 75종목 주식, 154종목 ETF )"])
        heading = doc.select_one("#new-stocks h2").get_text()
        self.assertEqual(heading, "오늘의 신규 등장 · 한국 4종목( 1종목 주식, 3종목 ETF ) · 미국 29종목( 5종목 주식, 24종목 ETF )")
        for country, label in (("kr", "11종목( 4종목 주식, 7종목 ETF )"),
                               ("us", "229종목( 75종목 주식, 154종목 ETF )")):
            intro = doc.select_one("#" + country).find_previous("p", class_="intro")
            self.assertTrue(intro.get_text().startswith(label))
        self.assertEqual(len(inventory(str(doc))["new"]), 33)

    def test_empty_and_default_asset_count_labels(self):
        self.assertEqual(security_count([]), "0종목( 0종목 주식, 0종목 ETF )")
        self.assertEqual(security_count([{}, {"asset_type": "주식"}, {"asset_type": "ETF"}]),
                         "3종목( 2종목 주식, 1종목 ETF )")
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
            self.assertEqual(len(cells),13)
            for index,key in enumerate(("cagr1y","cagr3y","cagr5y","cagr10y","cumulative_return","lifetime_cagr"),4):
                value=item.get(key)
                self.assertEqual(cells[index].get_text(),f"{value:.1f}" if value is not None else "-")
            self.assertEqual(cells[10].get_text(),row_size(dict(item,asset_type="ETF")))
            self.assertEqual(cells[11].get_text(),inception_text(item))
            self.assertEqual(cells[12].get_text(),elapsed_years_text(item.get("lifetime_years")))
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
        for table_id, count, columns in (("us",218,11),("kr",17,11),("new",10,10),("returns",20,13)):
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
        self.assertEqual(row_size({"asset_type":"ETF","aum":1.4,"mcap":9}),"1조원")
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

    def test_integer_krw_sizes_keep_the_one_trillion_boundary_and_aum_fallback(self):
        for value, expected in ((553.99,"553조원"),(1.0,"1조원"),(.99999,"9,999억원"),
                                (.55309,"5,530억원"),(.0003,"3억원")):
            with self.subTest(value=value):
                self.assertEqual(aum(value),expected)
                html=row_size_html({"asset_type":"주식","mcap":value})
                self.assertEqual("color:#c23932" in html,value<1)
        for invalid in (None,0,-1,float("nan"),float("inf")):
            with self.subTest(invalid=invalid):
                self.assertEqual(aum(invalid),"-")
                self.assertEqual(row_size({"asset_type":"ETF","aum":invalid,"mcap":.55309}),"5,530억원")

    def test_small_aum_is_red_in_every_security_section_and_native_delivery(self):
        from src import native_email
        import tempfile
        self.data["us"][0]["mcap"] = .55309
        self.data["kr"][0]["mcap"] = .55309
        self.data["etf_info"]["rows"][0]["aum"] = .55309
        body=render_email(**self.data)
        # Use a small complete inventory to keep this threshold regression bounded.
        data=dict(self.data,us=self.data["us"][:1],kr=self.data["kr"][:1],
                  new_us=self.data["us"][:1],new_kr=self.data["kr"][:1],
                  etf_info={"rows":self.data["etf_info"]["rows"][:1]})
        source=render_email(**data)
        with tempfile.TemporaryDirectory() as directory:
            delivery,_=native_email.prepare(source,inventory(source),directory)
        for html in (body,delivery):
            doc=BeautifulSoup(html,"html5lib")
            for table_id,column in (("us",5),("kr",5),("new",5),("returns",10)):
                cell=doc.select_one("#"+table_id+" tbody tr").find_all("td",recursive=False)[column]
                self.assertEqual(cell.get_text(),"5,530억원")
                self.assertEqual(cell.find("span")["style"],"color:#c23932")
    def test_stricter_delivery_size_guard(self):
        self.assertLessEqual(MAX_EMAIL_BYTES,85000)
        with self.assertRaises(RuntimeError):
            validate_size("가"*30000)
    def test_existing_drawn_flags_and_larger_fonts_are_preserved(self):
        body=render_email(**self.data)
        self.assertIn('src=cid:u',body)
        self.assertIn('src=cid:k',body)
        self.assertNotRegex(body,r"display\s*:\s*(?:flex|grid)")
        self.assertRegex(body,r"\.shell\{[^}]*font-size:15\.6px")
        self.assertNotIn("data-key=",body)
        self.assertNotIn("data-period=",body)

    def test_long_security_names_use_one_line_ellipsis_and_preserve_the_full_value(self):
        name = "한국 반도체 인공지능 인프라 솔루션 Semiconductor Infrastructure Holdings"
        for row in self.data["us"] + self.data["kr"] + self.data["etf_info"]["rows"]:
            row["name"] = name
        doc = BeautifulSoup(render_email(**self.data), "html5lib")
        for table_id in ("us", "kr", "new", "returns"):
            for row in doc.select("#" + table_id + " tbody tr"):
                cell = row.find_all("td", recursive=False)[3]
                self.assertNotIn("w", cell.get("class", []))
                self.assertEqual(cell.select_one(".nm").get_text(), name)
        self.assertIn("overflow:hidden;text-overflow:ellipsis;white-space:nowrap", CSS)

    def test_elapsed_years_show_the_used_fraction_and_missing_values(self):
        self.assertEqual(elapsed_years_text(10.398), "10.40년")
        self.assertEqual(elapsed_years_text(.498), "0.50년")
        for value in (None, 0, -1, float("nan"), float("inf")):
            self.assertEqual(elapsed_years_text(value), "-")

BASELINE_CSS = "\nbody{margin:0;background:#f2f5f8;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:15.6px;line-height:1.4}\ntable{border-collapse:collapse}a{color:#1260ad;text-decoration:none}\n.shell{max-width:1360px;margin:0 auto;padding:12px;color:#17263d;background:#f2f5f8;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:15.6px;line-height:1.4}.layout{width:100%;table-layout:fixed}\n.hero{background:#11243c;color:#fff;border-radius:9px;padding:12px 16px}.hero .eyebrow{display:none}\n.hero h1{font-size:24.7px;line-height:1.2;margin:0 0 5px}.date{font-size:14.3px;color:#c5d5e4}\n.hero .foot{font-size:13px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:6px;margin-top:7px}\n.summary{margin-top:8px;background:#fff;border:1px solid #dfe7ef;border-radius:8px;padding:8px 10px}\n.summary td{width:50%;padding:0 3px;vertical-align:top}.count{font-size:22.1px;font-weight:bold}\n.market{font-weight:bold;font-size:14.3px;margin-bottom:2px}.muted{font-size:13px;color:#667a90}\n.section{margin-top:14px}.section h2{margin:0;font-size:20.8px;line-height:1.25}\n.intro,.etf-caption{font-size:13px;color:#64778b;margin:4px 0 7px}\n.data-table{width:100%;table-layout:auto;background:#fff;border:1px solid #dce5ee;font-size:12.35px;line-height:1.25}\n.data-table th,.data-table td{white-space:nowrap;padding:3px 1px;text-align:left;vertical-align:middle}\n.data-table th{background:#163b68;color:#fff;font-weight:bold;font-size:13px;white-space:normal;word-break:keep-all}\n.data-table .w{white-space:normal;overflow-wrap:anywhere;word-break:break-word;max-width:180px}\n.data-table .nm{display:block;width:120px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}\n.stock-table th{background:#ee990b;color:#fff}\n.asset{display:inline-block;border-radius:3px;padding:1px 3px;font-size:11.7px;font-weight:bold}.s{background:#dff3ee;color:#087569}.e{background:#eee5fa;color:#753caf}\n.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}\n.data-table .n{text-align:right;font-variant-numeric:tabular-nums}\n.data-table .f{text-align:center;padding-left:1px;padding-right:1px}.f img{width:20px;height:auto;vertical-align:middle}\n.data-table .t{font-weight:bold}.data-table .y{background:#eaf1fb;font-weight:bold}\n.data-table th.y{background:#2b4665;color:#fff}.data-table .d{font-size:12.35px}\n.etf-comparison .data-table{font-size:13px}.metric-label{display:none}.m{display:block;font-size:13px;font-weight:bold;line-height:1.25}\n.etf-details{margin-top:12px}.etf-details h3{font-size:16.9px;margin:0 0 6px}\n.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}\n.new-section{border-top:3px solid #ee990b;padding-top:8px}.new-table th{background:#ee990b}.r{color:#c23932}.data-table .p1{color:#c23932}.data-table .p3{color:#245ba6}.data-table .p5{color:#087d67}.data-table .p10{color:#7944b0}.data-table .z{background:#f6f8fb}\n.new{background:#e6f3ed;color:#237353;border-radius:3px;padding:0 3px;margin-left:3px;font-size:10.4px;font-weight:bold}\n.notice{background:#fff4dc;color:#796438;border-radius:6px;padding:8px 10px;font-size:13px;margin:8px 0}\n.report-note{padding:8px 10px;background:#e8f0f8;border-radius:6px;color:#405d7a;font-size:13px}\n.notes{font-size:11.7px;line-height:1.5;color:#75869a;margin:8px 0}.footer{text-align:center;color:#8a9aab;font-size:11.7px;padding:16px 0 8px}\n"

if __name__=="__main__":
    unittest.main()


