"""Complete native delivery, field integrity and separate Gmail display hints."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from src import native_email
from src.email_layout import inventory, render_email, validate_etf_date_proof
from tools.preview_email import sample_data, make_stock, manifest_for
from src.main import validate_etf_market_dates


def fixture(count=218, long_names=False, etf_count=None):
    data = sample_data()
    if etf_count is not None:
        base = data["etf_info"]["rows"]
        rows = [dict(copy.deepcopy(base[index % len(base)]), ticker="ETF%03d" % index)
                for index in range(etf_count)]
        data["etf_info"].update(rows=rows, pool=etf_count, with_ret=etf_count,
                                eligible_count=etf_count, below_minimum_years=0)
    data["us"] = [make_stock("US%04d" % number, number=number) for number in range(count)]
    # Keep the full row/column coverage with realistic compact display labels;
    # the unrelated long-label overflow fixture belongs to browser layout QA.
    for row in data["us"] + data["kr"] + data["etf_info"]["rows"]:
        row["name"] = ("Global Semiconductor and Artificial Intelligence Infrastructure " + row["ticker"]
                       if long_names else row["ticker"])
        row["industry"] = "반도체"
        row["investment_area"] = "반도체"
        row["index"] = ["NASDAQ"] if row.get("market") == "US" else ["KOSPI"]
    data["new_us"] = data["us"][:29]
    data["new_kr"] = data["kr"][:4]
    data["etf_info"]["rows"][0].update(
        initial_adjusted_price=.0000123456789012, latest_adjusted_price=123456.987654,
        price_start_date="2016-05-19", price_end_date="2026-10-07",
        price_basis="Yahoo 제공 수정주가(auto_adjust)", price_currency="USD")
    source = render_email(**data)
    return source, inventory(source)


class NativeEmailTests(unittest.TestCase):
    def test_recent_and_ath_price_columns_survive_native_delivery_in_every_country_table(self):
        data = sample_data()
        for country in ("us", "kr"):
            data[country] = data[country][:1]
            data["new_" + country] = data[country]
            row = data[country][0]
            row.update(price=123.456789, ath_price=150.123456, ath_date="2026-08-21",
                       ath_start_date="2010-01-04", ath_end_date="2026-10-07",
                       ath_price_basis="검증용 동일 가격 기준",
                       gap=round((123.456789 / 150.123456 - 1) * 100, 2))
        source, manifest = render_email(**data), manifest_for(data)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, manifest, directory)
            self.assertEqual(native_email.verify_package(source, delivery, manifest, meta, directory), {})
            doc = BeautifulSoup(delivery, "html5lib")
            for table_id in ("us", "kr", "new-us", "new-kr"):
                table = doc.find("table", id=table_id)
                self.assertEqual([th.get_text() for th in table.select("thead th")][7:10],
                                 ["최근가격", "ATH가격", "ATH 괴리율"])
                cells = table.select_one("tbody tr").find_all("td", recursive=False)
                expected = ("123.46", "150.12") if table_id.endswith("us") else ("123", "150")
                self.assertEqual(tuple(cell.get_text() for cell in cells[7:9]), expected)
                self.assertIn("123.456789", cells[7]["title"])
                self.assertIn("150.123456", cells[8]["title"])
                self.assertIn("2026-08-21", cells[8].select_one(".cl")["title"])

    def test_native_comparison_only_etf_survives_without_entering_ath_country_table(self):
        data = sample_data()
        candidate = next(row for row in data["us"] if row.get("asset_type") == "ETF")
        candidate["gap"] = -28.6
        data["us"] = [row for row in data["us"] if row is not candidate]
        data["new_us"] = [row for row in data["us"] if row.get("asset_type") == "ETF"][:2]
        comparison = data["etf_info"]["rows"]
        source, manifest = render_email(**data), manifest_for(data)
        proof = validate_etf_market_dates(data["us"], data["kr"], data["info"], comparison_etfs=comparison)
        self.assertNotIn(candidate["ticker"], manifest["us"])
        self.assertIn(candidate["ticker"], manifest["etf"])
        record = next(row for row in proof["etfs"] if row["country"] == "US" and row["ticker"] == candidate["ticker"])
        self.assertFalse(record["in_ath_report"])
        self.assertTrue(record["in_comparison_universe"])
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, manifest, directory)
            self.assertEqual(native_email.verify_package(source, delivery, manifest, meta, directory), {})
            self.assertEqual(validate_etf_date_proof(delivery, manifest, proof), proof["market_dates"])
            self.assertEqual(inventory(delivery), manifest)

    def test_native_delivery_preserves_audited_market_dates_and_exact_price_dates(self):
        data = sample_data()
        data["new_us"] = [row for row in data["us"] if row.get("asset_type") == "ETF"][:2]
        data["new_kr"] = [row for row in data["kr"] if row.get("asset_type") == "ETF"][:2]
        data["info"]["us_last"] = "2026-10-08"
        source, manifest = render_email(**data), manifest_for(data)
        proof = validate_etf_market_dates(data["us"], data["kr"], data["info"])
        self.assertTrue(all(row["date_status"] == "latest_available" for row in proof["etfs"] if row["country"] == "US"))
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, manifest, directory)
            self.assertEqual(native_email.verify_package(source, delivery, manifest, meta, directory), {})
            for html in (source, delivery):
                self.assertEqual(validate_etf_date_proof(html, manifest, proof), proof["market_dates"])
                for row in BeautifulSoup(html, "html5lib").select("#returns tbody tr"):
                    cells = row.find_all("td", recursive=False)
                    self.assertEqual(len(cells), 19)
                    self.assertEqual(cells[14].get_text(), "26-10-07")
                    self.assertIn("2026-10-07", cells[14]["title"])
            original = BeautifulSoup(source, "html5lib").select_one("#etf-market-dates")
            delivered = BeautifulSoup(delivery, "html5lib").select_one("#etf-market-dates")
            self.assertEqual(str(delivered), str(original))

    def test_native_delivery_preserves_only_subunit_initial_price_red_text(self):
        data = sample_data()
        cases = ((.2051851749420166, "0.21", True), (.999, "1.00", True),
                 (.9999999999996, "1.00", True), (1.0, "1", False),
                 (1.999, "1", False), (None, "-", False))
        for row, (initial, _, _) in zip(data["etf_info"]["rows"], cases):
            row.update(initial_adjusted_price=initial, latest_adjusted_price=.5)
        source, manifest = render_email(**data), manifest_for(data)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, manifest, directory)
            self.assertEqual(native_email.verify_package(source, delivery, manifest, meta, directory), {})
            for html in (source, delivery):
                doc = BeautifulSoup(html, "html5lib")
                css = "".join(str(tag.string or "") for tag in doc.find_all("style"))
                self.assertIn(".initial-price-small{color:#c23932}", css)
                for tr, (_, text, red) in zip(doc.select("#returns tbody tr"), cases):
                    cells = tr.find_all("td", recursive=False)
                    markers = cells[15].select(".initial-price-small")
                    self.assertEqual(len(markers), int(red))
                    self.assertEqual(cells[15].get_text(), text)
                    self.assertEqual(cells[16].get_text(), "0")
                    self.assertIsNone(cells[16].select_one(".initial-price-small"))
                    self.assertEqual(cells[15]["title"], cells[15].select_one(".cl")["title"].split(" · ", 1)[1])

    def test_native_css_centers_the_two_date_columns_and_aligns_ytd_numbers(self):
        css = native_email._column_css()
        for column in (14, 15):
            self.assertIn(native_email._selectors((".v",), column) +
                          "{text-align:center;font-variant-numeric:normal;font-size:10.4975px}", css)
        self.assertIn(native_email._selectors((".v",), 16) +
                      "{text-align:right;font-variant-numeric:tabular-nums;font-size:11.05px}", css)
        self.assertIn(native_email._selectors((".v",), 5) +
                      "{text-align:right;font-variant-numeric:tabular-nums}", css)
        self.assertIn(native_email._selectors((".v",), 19) +
                      "{text-align:center}", css)
        source, expected = fixture(3)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, expected, directory)
            self.assertEqual(native_email.verify_package(source, delivery, expected, meta, directory), {})
            table = BeautifulSoup(delivery, "html5lib").select_one("#returns")
            headings = [cell.get_text() for cell in table.select("thead th")]
            self.assertEqual(headings, ["No", "국가", "티커", "종목명", "연환산", "연초", "1년", "2년", "3년", "10년",
                                        "누적", "누적년수", "시총", "설립일", "수익률기준일", "최초가", "최근가", "업종,투자", "운용방식"])
            self.assertIn("cagr", table.select("thead th")[4].get("class", []))
            css_text = "\n".join(str(style.string or "") for style in table.find_parent("html").find_all("style"))
            self.assertIn(".data-table .cagr{font-weight:bold;background:#fff2cc}", css_text)
            self.assertIn(".data-table th.cagr{background:#76551b;color:#fff}", css_text)
            for row in table.select("tbody tr"):
                cells = row.find_all("td", recursive=False)
                self.assertEqual([i for i, cell in enumerate(cells) if "cagr" in cell.get("class", [])], [4])

    def test_long_ticker_cells_keep_the_bold_clipping_parent_only_in_column_three(self):
        data = sample_data()
        data["us"][0]["ticker"] = "USLONGTICKER0000"
        data["kr"][0]["ticker"] = "KRLONGTICKER0000"
        data["etf_info"]["rows"][0]["ticker"] = "COMPARISONONLY0000"
        data["new_us"], data["new_kr"] = data["us"][:1], data["kr"][:1]
        source, manifest = render_email(**data), manifest_for(data)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, manifest, directory)
            self.assertEqual(native_email.verify_package(source, delivery, manifest, meta, directory), {})
        for html in (source, delivery):
            doc = BeautifulSoup(html, "html5lib")
            css = "".join(str(tag.string or "") for tag in doc.find_all("style"))
            self.assertIn(".data-table .t{font-weight:bold}", css)
            self.assertEqual({table.get("id") for table in doc.select("table.data-table")},
                             {"returns", "new-kr", "new-us", "kr", "us"})
            wanted = {"returns": "COMPARISONONLY0000", "us": "USLONGTICKER0000",
                      "new-us": "USLONGTICKER0000", "kr": "KRLONGTICKER0000",
                      "new-kr": "KRLONGTICKER0000"}
            for table in doc.select("table.data-table"):
                cells = table.select_one("tbody tr").find_all("td", recursive=False)
                self.assertIn("t", cells[2].get("class", []))
                ticker_link = cells[2].select_one(".cl a")
                self.assertEqual("".join(ticker_link.find_all(string=True, recursive=False)).strip(),
                                 wanted[table.get("id")])
                self.assertTrue(all("t" not in cell.get("class", [])
                                    for index, cell in enumerate(cells) if index != 2))

    def test_colgroup_widths_remain_exact_across_html5_transport_roundtrips(self):
        source = ('<table><colgroup><col style="width:3%"/>'
                  '<col style="width:126px"/><col/></colgroup>'
                  '<tbody><tr><td>1</td><td>value</td><td>end</td></tr></tbody></table>')
        original = BeautifulSoup(source, "html5lib")
        for _ in range(3):
            source = native_email._transport(source)
            parsed = BeautifulSoup(source, "html5lib")
            self.assertEqual([col.get("style") for col in parsed.select("col")],
                             ["width:3%", "width:126px", None])
            self.assertEqual(native_email.semantic_digest(parsed),
                             native_email.semantic_digest(original))
            source = str(parsed)

    def test_large_daily_reports_keep_every_native_row_and_value(self):
        for count in (240, 520):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                source, expected = fixture(count, long_names=True)
                delivery, meta = native_email.prepare(source, expected, directory)
                self.assertEqual(native_email.verify_package(source, delivery, expected, meta, directory), {})
                self.assertTrue(native_email.clipping_risk(delivery))
                self.assertEqual(inventory(delivery), expected)
                original = BeautifulSoup(source, "html5lib")
                doc = BeautifulSoup(delivery, "html5lib")
                self.assertEqual(native_email.semantic_digest(doc), native_email.semantic_digest(original))
                rows = doc.select("#us tbody tr")
                self.assertEqual(len(rows), count)
                self.assertEqual([row.find("td").get_text(strip=True) for row in rows],
                                 [str(number) for number in range(1, count + 1)])
                self.assertEqual(rows[-1].find_all("td")[3].get_text(),
                                 "Global Semiconductor and Artificial Intelligence Infrastructure US%04d" % (count - 1))
                self.assertLessEqual(meta["html_bytes"], native_email.MAX_HTML_BYTES)
                self.assertLessEqual(meta["canonical_bytes"], native_email.MAX_CANONICAL_BYTES)
                self.assertLessEqual(max(len(line.encode("utf-8")) for line in delivery.splitlines()), 998)

    def test_clipping_margins_are_hints_instead_of_delivery_failures(self):
        self.assertFalse(native_email.clipping_risk("<p>Small report</p>"))
        raw_large = "<p>" + "x" * native_email.CLIPPING_HTML_BYTES + "</p>"
        self.assertTrue(native_email.clipping_risk(raw_large))
        native_email.validate_delivery_size(raw_large)
        # Optional closing tags can expand a small wire body past the old guard.
        compact = "<table><tr>" + "<td>x" * 13000 + "</table>"
        self.assertLess(len(compact.encode("utf-8")), native_email.CLIPPING_HTML_BYTES)
        self.assertTrue(native_email.clipping_risk(compact))
        native_email.validate_delivery_size(compact)

    def test_all_218_us_rows_and_300_etfs_remain_native_with_every_field(self):
        source, expected = fixture(etf_count=300)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, expected, directory)
            self.assertEqual(native_email.verify_package(source, delivery, expected, meta, directory), {})
            self.assertEqual(inventory(delivery), expected)
            doc = BeautifulSoup(delivery, "html5lib")
            self.assertEqual(len(doc.select("#us tbody tr")), 218)
            self.assertEqual([row.find("td").get_text(strip=True) for row in doc.select("#us tbody tr")],
                             [str(number) for number in range(1, 219)])
            ranked = doc.select("#returns tbody tr")
            self.assertEqual(len(ranked), 300)
            self.assertEqual([row.find("td").get_text(strip=True) for row in ranked],
                             [str(number) for number in range(1, 301)])
            self.assertEqual(expected["etf"], ["ETF%03d" % number for number in range(300)])
            self.assertEqual([row.find_all("td", recursive=False)[2].get_text() for row in ranked],
                             expected["etf"])
            self.assertEqual(native_email.semantic_digest(doc),
                             native_email.semantic_digest(BeautifulSoup(source, "html5lib")))
            self.assertFalse(doc.select("#us-display"))
            self.assertTrue(all(image.get("src") in ("cid:u", "cid:k") for image in doc.find_all("img")))
            self.assertEqual(set(meta["native_tables"]), {"us", "kr", "new-kr", "new-us", "returns"})
            self.assertEqual([table.get("id") for table in doc.select("table.data-table")],
                             ["returns", "new-kr", "new-us", "kr", "us"])
            for table_id, count in (("new-kr", 4), ("new-us", 29)):
                rows = doc.select("#" + table_id + " tbody tr")
                self.assertEqual([row.find("td").get_text(strip=True) for row in rows],
                                 [str(number) for number in range(1, count + 1)])
            prices = doc.select_one("#returns tbody tr").find_all("td", recursive=False)[15:17]
            for cell, displayed, exact in zip(prices, ("0.00", "123,456"),
                                              ("1.23456789012e-05", "123456.987654")):
                self.assertEqual(cell.get_text(), displayed)
                self.assertIn("정확값 " + exact, cell["title"])
                self.assertIn("정확값 " + exact, cell.select_one(".cl")["title"])
            self.assertLess(len(delivery.encode("utf-8")), len(source.encode("utf-8")))
            self.assertLessEqual(meta["html_bytes"], native_email.MAX_HTML_BYTES)
            self.assertLessEqual(meta["canonical_bytes"], native_email.MAX_CANONICAL_BYTES)
            self.assertLess(meta["style_characters"], native_email.MAX_STYLE_CHARACTERS)
            self.assertLessEqual(max(len(line.encode("utf-8")) for line in delivery.splitlines()), 998)
            from src.main import compose_email_message
            message = compose_email_message(delivery, "test", "sender@example.test", "reader@example.test")
            wire = message.as_bytes()
            # Large reports stay complete inline without an automatic HTML file.
            self.assertFalse(any(part.get_content_disposition() == "attachment" for part in message.walk()))
            # Preserve the inline body exactly and enforce the actual SMTP budget.
            self.assertEqual([part.get_payload(decode=True).decode("utf-8").replace("\r\n", "\n")
                              for part in message.walk() if part.get_content_type() == "text/html"],
                             [delivery.replace("\r\n", "\n")])
            self.assertLessEqual(len(wire), 20000000)
            self.assertIn(b"Content-Type: text/plain", wire)
            self.assertTrue(doc.find("style").string)
            self.assertGreater(meta["style_characters"], 3000)

    def test_changed_number_field_link_or_flag_is_rejected_even_with_updated_metadata(self):
        source, expected = fixture(3)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, expected, directory)
            for kind in ("number", "field", "link", "flag", "style"):
                doc = BeautifulSoup(delivery, "html5lib")
                row = doc.select_one("#us tbody tr")
                cells = row.find_all("td", recursive=False)
                if kind == "number":
                    cells[0].string = "2"
                elif kind == "field":
                    cells[3].string = "Changed security"
                elif kind == "link":
                    cells[2].find("a")["href"] = "https://example.test"
                elif kind == "flag":
                    cells[1].find("img")["src"] = "cid:k"
                else:
                    doc.find("style").string += "td{font-size:1px}"
                altered = native_email._transport(str(doc))
                altered_meta = copy.deepcopy(meta)
                altered_meta["delivery_sha256"] = native_email.digest(altered.encode("utf-8"))
                altered_meta["html_bytes"], altered_meta["canonical_bytes"] = native_email.validate_delivery_size(altered)
                Path(directory, "email-delivery.html").write_text(altered, encoding="utf-8")
                Path(directory, "native-report.json").write_text(json.dumps(altered_meta), encoding="utf-8")
                with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                    native_email.verify_package(source, altered, expected, altered_meta, directory)

    def test_missing_source_row_or_number_is_rejected_before_preparation(self):
        source, expected = fixture(3)
        for kind in ("omitted", "number"):
            doc = BeautifulSoup(source, "html5lib")
            row = doc.select_one("#us tbody tr")
            if kind == "omitted":
                row.decompose()
            else:
                row.find("td").string = "9"
            with tempfile.TemporaryDirectory() as directory, self.subTest(kind=kind), self.assertRaises(RuntimeError):
                native_email.prepare(str(doc), expected, directory)

    def test_source_and_delivery_hard_budgets_still_reject_excessive_bodies(self):
        with self.assertRaisesRegex(RuntimeError, "preparation budget"):
            native_email.validate_source_size("x" * (native_email.MAX_SOURCE_BYTES + 1))
        with self.assertRaisesRegex(RuntimeError, "never remove candidates"):
            native_email.validate_delivery_size("<p>" + "x" * native_email.MAX_HTML_BYTES + "</p>")
        # Exercise the independent canonical guard with a smaller test budget.
        compact = "<table><tr>" + "<td>x" * 130 + "</table>"
        self.assertLess(len(compact.encode("utf-8")), native_email.MAX_HTML_BYTES)
        with patch.object(native_email, "MAX_CANONICAL_BYTES", 1000), self.assertRaisesRegex(RuntimeError, "delivery safety budget"):
            native_email.validate_delivery_size(compact)
        with self.assertRaisesRegex(RuntimeError, "style budget"):
            native_email.validate_delivery_size("<style>" + " " * native_email.MAX_STYLE_CHARACTERS + "</style>")

    def test_empty_report_and_publication_files_are_verified(self):
        data = sample_data()
        source = render_email([], [], data["info"], 1342)
        expected = inventory(source)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, expected, directory)
            self.assertEqual(native_email.verify_package(source, delivery, expected, meta, directory), {})
            Path(directory, "native-report.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                native_email.verify_package(source, delivery, expected, meta, directory)


if __name__ == "__main__":
    unittest.main()
