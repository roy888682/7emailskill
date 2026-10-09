"""Complete native delivery, field integrity and conservative Gmail budgets."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from src import native_email
from src.email_layout import inventory, render_email
from tools.preview_email import sample_data, make_stock


def fixture(count=218):
    data = sample_data()
    data["us"] = [make_stock("US%04d" % number, number=number) for number in range(count)]
    # Keep the full row/column coverage with realistic compact display labels;
    # the unrelated long-label overflow fixture belongs to browser layout QA.
    for row in data["us"] + data["kr"] + data["etf_info"]["rows"]:
        row["name"] = row["ticker"]
        row["industry"] = "반도체"
        row["investment_area"] = "반도체"
        row["index"] = ["NASDAQ"] if row.get("market") == "US" else ["KOSPI"]
    data["new_us"] = data["us"][:10]
    data["new_kr"] = data["kr"][:2]
    source = render_email(**data)
    return source, inventory(source)


class NativeEmailTests(unittest.TestCase):
    def test_all_218_us_rows_and_other_tables_remain_native_with_every_field(self):
        source, expected = fixture()
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = native_email.prepare(source, expected, directory)
            self.assertEqual(native_email.verify_package(source, delivery, expected, meta, directory), {})
            self.assertEqual(inventory(delivery), expected)
            doc = BeautifulSoup(delivery, "html5lib")
            self.assertEqual(len(doc.select("#us tbody tr")), 218)
            self.assertEqual([row.find("td").get_text(strip=True) for row in doc.select("#us tbody tr")],
                             [str(number) for number in range(1, 219)])
            self.assertEqual(native_email.semantic_digest(doc),
                             native_email.semantic_digest(BeautifulSoup(source, "html5lib")))
            self.assertFalse(doc.select("#us-display"))
            self.assertTrue(all(image.get("src") in ("cid:u", "cid:k") for image in doc.find_all("img")))
            self.assertEqual(set(meta["native_tables"]), {"us", "kr", "new", "returns"})
            self.assertLess(len(delivery.encode("utf-8")), len(source.encode("utf-8")))
            self.assertLessEqual(meta["html_bytes"], native_email.MAX_HTML_BYTES)
            self.assertLessEqual(meta["canonical_bytes"], native_email.MAX_CANONICAL_BYTES)
            self.assertLess(meta["style_characters"], native_email.MAX_STYLE_CHARACTERS)
            self.assertLessEqual(max(len(line.encode("utf-8")) for line in delivery.splitlines()), 998)

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

    def test_native_body_and_reparsed_body_both_have_size_guards(self):
        with self.assertRaisesRegex(RuntimeError, "never remove candidates"):
            native_email.validate_delivery_size("<p>" + "x" * native_email.MAX_HTML_BYTES + "</p>")
        # Optional closing tags can conceal a much larger reparsed HTML body.
        compact = "<table><tr>" + "<td>x" * 13000 + "</table>"
        self.assertLess(len(compact.encode("utf-8")), native_email.MAX_HTML_BYTES)
        with self.assertRaisesRegex(RuntimeError, "never remove candidates"):
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
