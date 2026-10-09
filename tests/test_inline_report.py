"""Numbered US row-image links and immutable complete delivery before SMTP."""
import copy
import io
import math
import random
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from src import email_layout, report_inline
from src.main import compose_email_message


def fixture(count=218):
    tickers = [f"US{i:04d}" for i in range(count)]
    urls = [("https://m.stock.naver.com/worldstock/etf/" + ticker + ".O" if index % 2 else
             "https://m.stock.naver.com/worldstock/stock/" + ticker + "/total")
            for index, ticker in enumerate(tickers)]
    table = ("<div class=\"section stock-section\"><h2>미국 ATH 후보</h2>"
             "<table class=\"data-table stock-table\" id=\"us\"><thead><tr>"
             "<th>No.</th><th>국가</th><th>티커</th></tr></thead><tbody>")
    for number, (ticker, url) in enumerate(zip(tickers, urls), 1):
        table += (f"<tr><td>{number}</td><td><img src=\"cid:u\" alt=\"\"></td>"
                  f"<td><a href=\"{url}\">{ticker}</a></td></tr>")
    table += "</tbody></table></div>"
    source = "<!DOCTYPE html><html><head><style>body{margin:0}</style></head><body>" + (table if count else "<p>미국 후보 없음</p>") + "</body></html>"
    expected = {"us": tickers, "kr": [], "new": [], "etf": []}
    if not count:
        return source, expected, None, []
    rows = [{"number": number, "ticker": ticker, "url": url,
             "top": 40.25 + (number - 1) * 20.5, "bottom": 40.25 + number * 20.5}
            for number, (ticker, url) in enumerate(zip(tickers, urls), 1)]
    image = Image.new("RGB", (1360, math.ceil(rows[-1]["bottom"]) + 2), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1359, 25), fill=(238, 153, 11))
    for number, row in enumerate(rows, 1):
        draw.rectangle((10, round(row["top"]) + 3, 200 + number, round(row["bottom"]) - 3),
                       fill=(number % 255, 50, 120))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return source, expected, stream.getvalue(), rows


class InlineReportTests(unittest.TestCase):
    def test_every_numbered_us_row_has_its_own_correct_naver_link_and_all_pixels(self):
        source, expected, png, rows = fixture()
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = report_inline.make_package(source, expected, png, rows, {"font_size": 9.5}, directory)
            assets = report_inline.verify_package(source, delivery, expected, meta, directory)
            doc = BeautifulSoup(delivery, "html5lib")
            anchors = doc.select("#us-display a")
            self.assertEqual(len(anchors), 218)
            self.assertEqual(meta["captured_font_size"], 9.5)
            self.assertIn("width:1360px;max-width:none", delivery)
            self.assertNotIn("#us-display img{display:block;width:100%", delivery)
            self.assertEqual([anchor["href"] for anchor in anchors], [row["url"] for row in rows])
            self.assertEqual([image["alt"] for image in doc.select("#us-display a img")],
                             [f'{row["number"]}. {row["ticker"]}' for row in rows])
            self.assertEqual([link["number"] for link in meta["links"]], list(range(1, 219)))
            self.assertEqual([link["ticker"] for link in meta["links"]], expected["us"])
            self.assertEqual([link["url"] for link in meta["links"]], [row["url"] for row in rows])
            self.assertEqual(len(assets), 220)  # header + 218 independently linked rows + tail
            self.assertIn("us-report-218", assets)
            self.assertFalse(doc.select("#us"))
            self.assertFalse(any(image.has_attr("style") for image in doc.select("#us-display img")))
            self.assertLess(len(delivery.encode("utf-8")), report_inline.MAX_HTML_BYTES)
            self.assertLessEqual(max(len(line.encode("utf-8")) for line in delivery.splitlines()), 998)
            canvas = Image.new("RGB", (meta["width"], meta["height"]))
            for asset in meta["assets"]:
                image = Image.open(io.BytesIO(assets[asset["cid"]])).convert("RGB")
                canvas.paste(image, (0, asset["top"]))
            self.assertEqual(canvas.tobytes(), Image.open(io.BytesIO(png)).convert("RGB").tobytes())
            for row, asset in zip(rows, [asset for asset in meta["assets"] if asset["kind"] == "row"]):
                self.assertLessEqual(asset["top"], (row["top"] + row["bottom"]) / 2)
                self.assertGreater(asset["bottom"], (row["top"] + row["bottom"]) / 2)

    def test_missing_reordered_changed_or_relinked_report_is_rejected(self):
        source, expected, png, rows = fixture(4)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = report_inline.make_package(source, expected, png, rows, {"font_size": 9.5}, directory)
            for change in ("omitted", "reordered", "changed", "number", "ticker", "url", "links", "font"):
                altered = copy.deepcopy(meta)
                if change == "omitted":
                    altered["assets"] = altered["assets"][:-1]
                elif change == "reordered":
                    altered["assets"].reverse()
                elif change == "changed":
                    altered["assets"][0]["sha256"] = "bad"
                elif change == "number":
                    altered["rows"][0]["number"] = 2
                elif change == "ticker":
                    altered["rows"][0]["ticker"] = "MISSING"
                elif change == "url":
                    altered["rows"][0]["url"] = rows[1]["url"]
                elif change == "font":
                    altered["captured_font_size"] = 8
                else:
                    altered["links"].reverse()
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    report_inline.verify_package(source, delivery, expected, altered, directory)
            altered_html = delivery.replace(rows[0]["url"], rows[1]["url"], 1)
            altered = copy.deepcopy(meta)
            altered["delivery_sha256"] = report_inline.digest(altered_html.encode("utf-8"))
            with self.assertRaisesRegex(RuntimeError, "clickable"):
                report_inline.verify_package(source, altered_html, expected, altered, directory)
            with self.assertRaises(RuntimeError):
                report_inline.verify_package(source + "changed", delivery, expected, meta, directory)
            first_asset = meta["assets"][0]
            path = Path(directory) / first_asset["path"]
            changed_png = Image.open(path).convert("RGB")
            changed_png.putpixel((0, 0), (1, 2, 3))
            changed_png.save(path)
            with self.assertRaises(RuntimeError):
                report_inline.verify_package(source, delivery, expected, meta, directory)

    def test_source_numbers_row_numbers_and_naver_url_binding_are_mandatory(self):
        source, expected, png, rows = fixture(3)
        with tempfile.TemporaryDirectory() as directory:
            bad_sources = [source.replace("<td>1</td>", "<td>2</td>", 1),
                           source.replace("https://m.stock.naver.com", "https://example.test", 1)]
            for altered_source in bad_sources:
                with self.assertRaises(RuntimeError):
                    report_inline.make_package(altered_source, expected, png, rows, {"font_size": 9.5}, directory)
            for key, value in (("number", 2), ("ticker", "OTHER"), ("url", rows[1]["url"]),
                               ("top", float("nan")), ("bottom", 10000)):
                altered = copy.deepcopy(rows)
                altered[0][key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    report_inline.make_package(source, expected, png, altered, {"font_size": 9.5}, directory)

    def test_empty_us_report_remains_valid(self):
        source, expected, png, rows = fixture(0)
        with tempfile.TemporaryDirectory() as directory:
            delivery, meta = report_inline.make_package(source, expected, png, rows, {"font_size": 9.5}, directory)
            self.assertEqual(delivery, source)
            self.assertEqual(meta["links"], [])
            self.assertEqual(report_inline.verify_package(source, delivery, expected, meta, directory), {})

    def test_row_images_are_inline_with_no_attachment_filename(self):
        rng = random.Random(7)
        image = Image.frombytes("RGB", (600, 200), rng.randbytes(600 * 200 * 3))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        png = stream.getvalue()
        html = '<a href="https://m.stock.naver.com/worldstock/etf/TQQQ.O"><img src="cid:us-report-218" alt="218. TQQQ"></a>'
        msg = compose_email_message(html, "test", "a@example.test", "b@example.test",
                                    {"us-report-218": png})
        self.assertGreater(len(msg.as_bytes()), 95000)
        self.assertFalse(any(part.get_content_disposition() == "attachment" or part.get_filename()
                             for part in msg.walk()))
        body = next(part for part in msg.walk() if part.get_content_type() == "text/html")
        self.assertEqual(body.get_payload(decode=True).decode("utf-8"), html)
        part = next(part for part in msg.walk() if part.get("Content-ID") == "<us-report-218>")
        self.assertEqual(part.get_payload(decode=True), png)
        self.assertEqual(part.get_content_disposition(), "inline")

    def test_oversize_text_cannot_bypass_the_small_html_budget(self):
        with self.assertRaisesRegex(RuntimeError, "never remove candidates"):
            report_inline.validate_delivery_size("<p>" + "x" * (report_inline.MAX_HTML_BYTES + 1) + "</p>")


if __name__ == "__main__":
    unittest.main()
