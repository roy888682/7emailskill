"""Regressions for the restored 38-security desktop table and direct delivery."""
import copy
import unittest
from datetime import date
from bs4 import BeautifulSoup
from src.email_layout import (render_email, etf_section_html, inception_text,
                              row_size, row_size_html, aum, industry_text, inventory, validate_size,
                              validate_inventory, MAX_EMAIL_BYTES, CSS, compact_transport_html, security_count,
                              elapsed_years_text, price_text, brief_investment_text,
                              validate_etf_date_proof)
from tools.preview_email import sample_data, make_stock, manifest_for

class EmailLayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.data["us"].extend(make_stock(f"EXTRA{i}", number=i) for i in range(5))
        self.data["new_us"] = self.data["us"][:29]
        self.data["new_kr"] = self.data["kr"][:4]

    def market_proof(self, data=None):
        data = data or self.data
        records = [dict(row, country=country) for country, items in (("US", data["us"]), ("KR", data["kr"]))
                   for row in items if row.get("asset_type") == "ETF"]
        return {"version": 1, "market_dates": {"US": "2026-10-07", "KR": "2026-10-07"},
                "etfs": records,
                "counts": {country: sum(row["country"] == country for row in records) for country in ("US", "KR")}}

    def test_country_market_dates_are_visible_and_survive_compaction(self):
        self.data["info"]["kr_last"] = date(2026, 10, 8)
        doc = BeautifulSoup(render_email(**self.data), "html5lib")
        for country, label, expected in (("KR", "한국", "2026-10-08"), ("US", "미국", "2026-10-07")):
            node = doc.select_one('#etf-market-dates [aria-label="' + country + ' market date"]')
            self.assertEqual(node["title"], expected)
            self.assertEqual(node.get_text(), f"{label} 수익률 기준일 {expected}")
        self.assertIn("복리 연환산(CAGR)", doc.get_text())
        self.assertIn("원금과 수익이 매년 함께 재투자", doc.get_text())

    def test_full_etf_market_proof_covers_even_funds_outside_the_comparison(self):
        extra = dict(next(row for row in self.data["us"] if row.get("asset_type") == "ETF"), ticker="OUTSIDE100")
        self.data["us"].append(extra)
        source = render_email(**self.data)
        manifest = manifest_for(self.data)
        proof = self.market_proof()
        self.assertNotIn("OUTSIDE100", manifest["etf"])
        self.assertEqual(validate_etf_date_proof(source, manifest, proof), proof["market_dates"])
        stale = copy.deepcopy(proof)
        next(row for row in stale["etfs"] if row["ticker"] == "OUTSIDE100")["price_end_date"] = "2026-10-06"
        with self.assertRaisesRegex(RuntimeError, "price date differs"):
            validate_etf_date_proof(source, manifest, stale)
        omitted = copy.deepcopy(proof)
        omitted["etfs"] = [row for row in omitted["etfs"] if row["ticker"] != "OUTSIDE100"]
        omitted["counts"]["US"] -= 1
        with self.assertRaisesRegex(RuntimeError, "cover every ETF"):
            validate_etf_date_proof(source, manifest, omitted)

    def test_new_badges_do_not_change_audited_etf_ticker_membership(self):
        self.data["new_us"] = [next(row for row in self.data["us"] if row.get("asset_type") == "ETF")]
        self.data["new_kr"] = [next(row for row in self.data["kr"] if row.get("asset_type") == "ETF")]
        source = render_email(**self.data)
        self.assertIn("신규", BeautifulSoup(source, "html5lib").select_one("#us tbody").get_text())
        proof = self.market_proof()
        self.assertEqual(validate_etf_date_proof(source, manifest_for(self.data), proof), proof["market_dates"])

    def test_market_proof_rejects_changed_caption_price_date_or_precise_price(self):
        source = render_email(**self.data)
        manifest, proof = manifest_for(self.data), self.market_proof()
        for field in ("caption", "date", "price"):
            with self.subTest(field=field):
                doc = BeautifulSoup(source, "html5lib")
                if field == "caption":
                    node = doc.select_one('#etf-market-dates [aria-label="US market date"]')
                    node["title"] = "2026-10-06"
                else:
                    cell = doc.select_one("#returns tbody tr").find_all("td", recursive=False)[11]
                    if field == "date":
                        cell["title"] = cell["title"].replace("2026-10-07", "2026-10-06")
                    else:
                        cell["title"] = cell["title"].replace("정확값 ", "정확값 9", 1)
                with self.assertRaises(RuntimeError):
                    validate_etf_date_proof(str(doc), manifest, proof)
    def test_includes_all_218_us_and_17_kr_rows(self):
        body = render_email(**self.data)
        actual = inventory(body)
        expected = {"us":[row["ticker"] for row in self.data["us"]],
                    "kr":[row["ticker"] for row in self.data["kr"]],
                    "new":["KR:"+row["ticker"] for row in self.data["new_kr"]] +
                          ["US:"+row["ticker"] for row in self.data["new_us"]],
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
        self.assertIsNone(doc.find("table", id="new"))
        for table_id, items in (("new-kr", new_kr), ("new-us", new_us)):
            rows = doc.select("#" + table_id + " tbody tr")
            self.assertEqual(len(rows), len(items))
            self.assertEqual([row.find_all("td", recursive=False)[0].get_text(strip=True) for row in rows],
                             [str(rank) for rank in range(1, len(items) + 1)])
            self.assertEqual([row.find_all("td", recursive=False)[2].get_text(strip=True) for row in rows],
                             [item["ticker"] for item in items])
        self.assertEqual(inventory(str(doc))["new"],
                         ["KR:" + row["ticker"] for row in new_kr] +
                         ["US:" + row["ticker"] for row in new_us])

    def test_empty_and_default_asset_count_labels(self):
        self.assertEqual(security_count([]), "0종목( 0종목 주식, 0종목 ETF )")
        self.assertEqual(security_count([{}, {"asset_type": "주식"}, {"asset_type": "ETF"}]),
                         "3종목( 2종목 주식, 1종목 ETF )")
    def test_headers_are_centered_and_numeric_cells_keep_right_alignment(self):
        body = render_email(**self.data)
        self.assertIn("text-align:left", body)
        self.assertIn("text-align:right;font-variant-numeric:tabular-nums", body)
        self.assertNotIn(".tbl", body)
        self.assertIn("text-align:center!important", body)
        doc = BeautifulSoup(body, "html5lib")
        self.assertNotIn("n",doc.select("#us th")[3].get("class",[]))
    def test_new_list_is_complete_and_precedes_etf(self):
        body = render_email(**self.data)
        self.assertEqual(inventory(body)["new"],
                         ["KR:"+row["ticker"] for row in self.data["new_kr"]] +
                         ["US:"+row["ticker"] for row in self.data["new_us"]])
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
            self.assertEqual(len(cells),16)
            for index,key in zip((5,6,7,8,9,12),("cagr1y","cagr3y","cagr5y","cagr10y","cumulative_return","lifetime_cagr")):
                value=item.get(key)
                self.assertEqual(cells[index].get_text(),f"{value:.1f}" if value is not None else "-")
            self.assertEqual(cells[4].get_text(),brief_investment_text(item))
            self.assertEqual(cells[10].get_text(),price_text(item.get("initial_adjusted_price")))
            self.assertEqual(cells[11].get_text(),price_text(item.get("latest_adjusted_price")))
            self.assertEqual(cells[13].get_text(),row_size(dict(item,asset_type="ETF")))
            self.assertEqual(cells[14].get_text(),inception_text(item))
            self.assertEqual(cells[15].get_text(),elapsed_years_text(item.get("lifetime_years")))
            self.assertEqual([cells[i].get("class",[])[-1] for i in range(5,9)],["p1","p3","p5","p10"])
    def test_signed_values_and_different_asset_badges_are_preserved(self):
        body = render_email(**self.data)
        doc=BeautifulSoup(body,"html5lib")
        self.assertTrue(doc.select(".stock-table i, .new-table i"))
        self.assertTrue(doc.select(".stock-table b, .new-table b"))
        for row in doc.select("#us tbody tr, #kr tbody tr, #new-kr tbody tr, #new-us tbody tr"):
            cells=row.find_all("td",recursive=False)
            self.assertIn("r",cells[7].get("class",[]))
            self.assertIn("r",cells[8].get("class",[]))
    def test_every_security_table_has_sequential_no_column(self):
        body = render_email(**self.data)
        doc = BeautifulSoup(body, "html5lib")
        for table_id, count, columns in (("us",218,11),("kr",17,11),
                                         ("new-kr",4,10),("new-us",29,10),("returns",20,16)):
            table = doc.find("table", id=table_id)
            self.assertEqual(table.select_one("thead th").get_text(strip=True), "No.")
            rows = table.select("tbody tr")
            self.assertEqual(len(rows), count)
            self.assertEqual([row.find_all("td",recursive=False)[0].get_text(strip=True) for row in rows],
                             [str(number) for number in range(1,count+1)])
            self.assertTrue(all(len(row.find_all("td",recursive=False)) == columns for row in rows))

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
        for table_id in ("us","kr","new-kr","new-us","returns"):
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
            for table_id,column in (("us",6),("kr",6),("new-kr",6),("new-us",6),("returns",13)):
                cell=doc.select_one("#"+table_id+" tbody tr").find_all("td",recursive=False)[column]
                self.assertEqual(cell.get_text(),"5,530억원")
                self.assertEqual(cell.find("span",style=True)["style"],"color:#c23932")
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
        for table_id in ("us", "kr", "new-kr", "new-us", "returns"):
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

    def test_industry_column_uses_seventy_percent_width_and_preserves_every_label(self):
        body = render_email(**self.data)
        doc = BeautifulSoup(body, "html5lib")
        for table_id in ("us", "kr", "new-kr", "new-us"):
            table = doc.select_one("#" + table_id)
            self.assertIn("iw", table.select("thead th")[4].get("class", []))
            for row in table.select("tbody tr"):
                cell = row.find_all("td", recursive=False)[4]
                self.assertIn("iw", cell.get("class", []))
                self.assertEqual(cell.select_one(".iwc").get_text(), cell.get_text())
        self.assertIn(".data-table .iw{width:126px;max-width:126px}", CSS)

    def test_top_hundred_table_keeps_the_last_rank_and_all_sixteen_columns(self):
        base = self.data["etf_info"]["rows"][0]
        rows = [dict(base, ticker=f"ETF{index:03d}", lifetime_cagr=100-index)
                for index in range(100)]
        data = dict(self.data, etf_info={"rows": rows, "pool": 125, "with_ret": 125})
        doc = BeautifulSoup(render_email(**data), "html5lib")
        rendered = doc.select("#returns tbody tr")
        self.assertEqual(len(rendered), 100)
        self.assertTrue(all(len(row.find_all("td", recursive=False)) == 16 for row in rendered))
        self.assertEqual(rendered[-1].find_all("td", recursive=False)[0].get_text(), "100")
        self.assertEqual(inventory(str(doc))["etf"], [row["ticker"] for row in rows])
        self.assertIn("내림차순 · 상위 100개", doc.get_text())

    def test_all_columns_retain_full_values_in_one_line_clipping_containers(self):
        doc = BeautifulSoup(render_email(**self.data), "html5lib")
        for cell in doc.select(".data-table td, .data-table th"):
            clip = cell.select_one(".cl,.nm")
            self.assertIsNotNone(clip)
            self.assertEqual(clip.get_text(), cell.get_text())
            self.assertIn(cell.get_text(), clip.get("title", ""))
        self.assertIn("border-right:1px solid #000", CSS)
        self.assertIn("table-layout:fixed", CSS)

    def test_column_widths_survive_repeated_html_transport_compaction(self):
        source = render_email(**self.data)
        doc = BeautifulSoup(source, "html5lib")
        for table_id, column, width in (("us",6,"84px"),("kr",6,"84px"),
                                         ("new-kr",6,"84px"),("new-us",6,"84px"),("returns",13,"96px")):
            self.assertEqual(doc.select_one("#" + table_id).select("col")[column].get("style"), "width:" + width)
        for table_id in ("new-kr", "new-us"):
            self.assertEqual(doc.select_one("#" + table_id).select("col")[3].get("style"), "width:19%")
        expected = [node.get("style") for node in doc.select("col")]
        self.assertTrue(expected)
        self.assertTrue(all(not value.endswith("/") for value in expected if value))
        for _ in range(3):
            source = compact_transport_html(source)
            self.assertEqual([node.get("style") for node in BeautifulSoup(source, "html5lib").select("col")], expected)

    def test_price_columns_show_integer_prices_and_preserve_exact_verification_values(self):
        item = self.data["etf_info"]["rows"][0]
        item.update(initial_adjusted_price=.0000123456789012, latest_adjusted_price=123456.987654,
                    price_start_date="2016-05-19", price_end_date="2026-10-07",
                    price_basis="Yahoo 제공 수정주가(auto_adjust)", price_currency="USD")
        doc = BeautifulSoup(render_email(**self.data), "html5lib")
        self.assertEqual([cell.get_text() for cell in doc.select("#returns thead th")][10:12],
                         ["최초주가", "최근주가"])
        cells = doc.select_one("#returns tbody tr").find_all("td", recursive=False)
        for index,key,date_value in ((10,"initial_adjusted_price","2016-05-19"),(11,"latest_adjusted_price","2026-10-07")):
            self.assertEqual(cells[index].get_text(), "0" if index == 10 else "123,456")
            expected_detail = (f'정확값 {format(item[key], ".12g")} · {date_value} · '
                               'Yahoo 제공 수정주가(auto_adjust) · USD')
            self.assertEqual(cells[index]["title"], expected_detail)
            self.assertIn(expected_detail, cells[index].select_one(".cl")["title"])
        for value, expected in ((1234.999, "1,234"), (1.999, "1"), (.999, "0")):
            self.assertEqual(price_text(value), expected)
        for value in (None, 0, -1, float("nan"), float("inf"), True):
            self.assertEqual(price_text(value), "-")
        self.assertEqual(inception_text({"inception":"2026-10-02","inception_verified":False}), "미확인")

    def test_brief_etf_investment_labels_are_next_to_the_security_name(self):
        self.assertEqual(brief_investment_text({"asset_type":"ETF","etf_index":"NASDAQ-100 Index"}), "나스닥100")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","name":"KODEX 반도체","market":"KOSPI"}), "한국반도체")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","name":"글로벌반도체","market":"KOSPI"}), "글로벌반도체")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","ticker":"DFAC"}), "미국주식·액티브")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","ticker":"QQQ"}), "나스닥100")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","ticker":"TQQQ"}), "나스닥100·일일3배")
        self.assertEqual(brief_investment_text({"asset_type":"ETF","name":"Goldman Sachs ActiveBeta US Large Cap Equity ETF","investment_area":"미국대형주"}), "미국대형주")

BASELINE_CSS = "\nbody{margin:0;background:#f2f5f8;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:15.6px;line-height:1.4}\ntable{border-collapse:collapse}a{color:#1260ad;text-decoration:none}\n.shell{max-width:1360px;margin:0 auto;padding:12px;color:#17263d;background:#f2f5f8;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:15.6px;line-height:1.4}.layout{width:100%;table-layout:fixed}\n.hero{background:#11243c;color:#fff;border-radius:9px;padding:12px 16px}.hero .eyebrow{display:none}\n.hero h1{font-size:24.7px;line-height:1.2;margin:0 0 5px}.date{font-size:14.3px;color:#c5d5e4}\n.hero .foot{font-size:13px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:6px;margin-top:7px}\n.summary{margin-top:8px;background:#fff;border:1px solid #dfe7ef;border-radius:8px;padding:8px 10px}\n.summary td{width:50%;padding:0 3px;vertical-align:top}.count{font-size:22.1px;font-weight:bold}\n.market{font-weight:bold;font-size:14.3px;margin-bottom:2px}.muted{font-size:13px;color:#667a90}\n.section{margin-top:14px}.section h2{margin:0;font-size:20.8px;line-height:1.25}\n.intro,.etf-caption{font-size:13px;color:#64778b;margin:4px 0 7px}\n.data-table{width:100%;table-layout:fixed;background:#fff;border:1px solid #dce5ee;font-size:12.35px;line-height:1.25}\n.data-table th,.data-table td{white-space:nowrap;overflow:hidden;padding:3px 1px;text-align:left;vertical-align:middle;border-right:1px solid #000}\n.data-table th:last-child,.data-table td:last-child{border-right:0}\n.data-table th{background:#163b68;color:#fff;font-weight:bold;font-size:13px;white-space:nowrap;text-align:center!important}\n.data-table .cl,.data-table .nm,.data-table .iwc{display:block;width:100%;max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n.data-table .iw{width:126px;max-width:126px}\n.data-table .nm{text-align:left}\n.stock-table th{background:#ee990b;color:#fff}\n.asset{display:inline-block;border-radius:3px;padding:1px 3px;font-size:11.7px;font-weight:bold}.s{background:#dff3ee;color:#087569}.e{background:#eee5fa;color:#753caf}\n.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}\n.data-table .n{text-align:right;font-variant-numeric:tabular-nums}\n.data-table .f{text-align:center;padding-left:1px;padding-right:1px}.f img{width:20px;height:auto;vertical-align:middle}\n.data-table .t{font-weight:bold}.data-table .y{background:#eaf1fb;font-weight:bold}\n.data-table th.y{background:#2b4665;color:#fff}.data-table .d{font-size:12.35px}\n.etf-comparison .data-table{font-size:13px}.metric-label{display:none}.m{display:block;font-size:13px;font-weight:bold;line-height:1.25}\n.etf-details{margin-top:12px}.etf-details h3{font-size:16.9px;margin:0 0 6px}\n.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}\n.new-section{border-top:3px solid #ee990b;padding-top:8px}.new-table th{background:#ee990b}.r{color:#c23932}.data-table .p1{color:#c23932}.data-table .p3{color:#245ba6}.data-table .p5{color:#087d67}.data-table .p10{color:#7944b0}.data-table .z{background:#f6f8fb}\n.new{background:#e6f3ed;color:#237353;border-radius:3px;padding:0 3px;margin-left:3px;font-size:10.4px;font-weight:bold}\n.notice{background:#fff4dc;color:#796438;border-radius:6px;padding:8px 10px;font-size:13px;margin:8px 0}\n.report-note{padding:8px 10px;background:#e8f0f8;border-radius:6px;color:#405d7a;font-size:13px}\n.notes{font-size:11.7px;line-height:1.5;color:#75869a;margin:8px 0}.footer{text-align:center;color:#8a9aab;font-size:11.7px;padding:16px 0 8px}\n"

if __name__=="__main__":
    unittest.main()


