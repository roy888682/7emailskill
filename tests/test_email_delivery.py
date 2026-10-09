"""Delivery regressions: every candidate in one body and zero attachments."""
import os
import tempfile
import unittest
from email import message_from_bytes
from pathlib import Path
from unittest.mock import patch

from src.main import compose_email_message, send_email, build_subject, main, send_prepared
from tools.preview_email import sample_data, make_stock
from datetime import date
import re
from src.email_layout import inventory, render_email, validate_size
from src import report_inline


class EmailDeliveryTests(unittest.TestCase):
    def test_inline_cid_flags_have_matching_png_parts(self):
        html = '<img src="cid:u"><img src="cid:k"><h1>ETF</h1>'
        message = compose_email_message(html, "test", "sender@example.test", "reader@example.test")
        parts = list(message.walk())
        images = [part for part in parts if part.get_content_type() == "image/png"]
        self.assertEqual({part["Content-ID"] for part in images}, {"<u>", "<k>"})
        self.assertEqual(len(images), 2)
        self.assertTrue(any(part.get_content_type() == "multipart/related" for part in parts))
        for part in images:
            self.assertEqual(part.get_content_disposition(), "inline")
            self.assertTrue(part.get_payload(decode=True).startswith(b"\x89PNG\r\n\x1a\n"))
        body = [part for part in parts if part.get_content_type() == "text/html"][0]
        self.assertEqual(body.get_payload(decode=True).decode("utf-8"), html)
        self.assertTrue(any(part.get_content_type() == "text/plain" for part in parts))
        self.assertTrue(message["Date"])
        self.assertTrue(message["Message-ID"])
        self.assertLessEqual(len(message.as_bytes()), 95000)

    def test_actual_serialized_size_and_smtp_lines_are_bounded(self):
        # UTF-8 content is transported directly rather than inflated with Base64.
        html = "<p>한글 표</p>\n" * 1000
        message = compose_email_message(html,"test","a@example.test","b@example.test")
        wire = message.as_bytes()
        parsed = message_from_bytes(wire)
        body = next(part for part in parsed.walk() if part.get_content_type()=="text/html")
        self.assertEqual(body["Content-Transfer-Encoding"],"8bit")
        self.assertEqual(body.get_payload(decode=True).decode("utf-8").replace("\r\n","\n"),html)
        self.assertLessEqual(len(wire),95000)
        self.assertLessEqual(max(map(len,wire.split(b"\r\n"))),998)
        with self.assertRaisesRegex(RuntimeError,"SMTP line limit"):
            compose_email_message("x"*999,"test","a@example.test","b@example.test")

    def test_oversized_html_is_rejected_before_smtp_without_dropping_rows(self):
        html = '<img src="cid:u">' + "가" * 85000
        with self.assertRaisesRegex(RuntimeError, "never remove candidates"):
            compose_email_message(html, "test", "a@example.test", "b@example.test")
        with patch.dict(os.environ, {"GMAIL_USER":"a", "GMAIL_APP_PASSWORD":"b"}):
            with patch("src.main.smtplib.SMTP_SSL") as smtp:
                with self.assertRaises(RuntimeError):
                    send_email(html, "test")
                smtp.assert_not_called()

    def test_main_sends_all_218_us_and_17_kr_in_one_message(self):
        data = sample_data()
        data["us"].extend(make_stock(f"EXTRA{i}", number=i) for i in range(5))
        info = dict(data["info"], us_last=date(2026,10,8), kr_last=date(2026,10,8))
        with (
            patch("src.main.get_trading_info", return_value=info),
            patch("src.main.get_usd_krw", return_value=1342),
            patch("src.main.get_market_indices", return_value=data["indices"]),
            patch("src.main.get_us_ath", return_value=data["us"]),
            patch("src.main.get_kr_ath", return_value=data["kr"]),
            patch("src.main.load_snapshots", return_value={}),
            patch("src.main.save_snapshots"),
            patch("src.main.send_email") as send,
        ):
            main()
        send.assert_called_once()
        self.assertEqual(len(send.call_args.args), 2)
        html = send.call_args.args[0]
        keys = ["KR:" + x for x in inventory(html)["kr"]] + ["US:" + x for x in inventory(html)["us"]]
        self.assertEqual(keys, ["KR:" + r["ticker"] for r in data["kr"]] + ["US:" + r["ticker"] for r in data["us"]])
        self.assertEqual(sum(key.startswith("US:") for key in keys), 218)
        self.assertEqual(sum(key.startswith("KR:") for key in keys), 17)
        self.assertNotIn("첨부", html)

    def test_prepared_delivery_requires_complete_matching_browser_proof(self):
        import hashlib, json
        data = sample_data()
        html = render_email([], [], data["info"], 1342)
        manifest = inventory(html)
        proof = {"sha256":hashlib.sha256(html.encode("utf-8")).hexdigest(),
                 "all_passed":True, "layout_unchanged":True, "html_bytes":len(html.encode("utf-8")),
                 "counts":{key:len(values) for key,values in manifest.items()},
                 "hosts":["standalone","gmail"], "viewports":[900,1024,1280,1600,1920]}
        with tempfile.TemporaryDirectory() as directory:
            original = os.getcwd()
            try:
                os.chdir(directory)
                Path("work").mkdir()
                Path("work/email-body.html").write_text(html, encoding="utf-8")
                Path("work/report-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                Path("work/email-subject.txt").write_text("test", encoding="utf-8")
                Path("work/pending-snapshots.json").write_text("{}", encoding="utf-8")
                delivery,package=report_inline.make_package(html,manifest,None,[],{},Path("work"))
                proof.update(delivery_sha256=report_inline.digest(delivery.encode("utf-8")),
                             package_sha256=report_inline.digest(Path("work/inline-report.json").read_bytes()),
                             delivery_checked=True,delivery_viewports=[1600,1920])
                for change in ({"delivery_checked":False}, {"delivery_sha256":"bad"}, {"package_sha256":"bad"}, {"delivery_viewports":[]}, {"all_passed":False}, {"layout_unchanged":False}, {"html_bytes":1}, {"hosts":["standalone"]},
                               {"viewports":[1024]}, {"counts":{}}, {"sha256":"bad"}):
                    with self.subTest(change=change):
                        Path("work/preview-passed.json").write_text(json.dumps(dict(proof, **change)), encoding="utf-8")
                        with patch("src.main.send_email") as send:
                            with self.assertRaises(RuntimeError):
                                send_prepared()
                            send.assert_not_called()
                Path("work/preview-passed.json").write_text(json.dumps(proof), encoding="utf-8")
                with patch("src.main.send_email") as send, patch("src.main.save_snapshots"):
                    send_prepared()
                    send.assert_called_once_with(html, "test",inline_images={},source_html=html)
            finally:
                os.chdir(original)

    def test_subject_uses_country_names_instead_of_flag_letter_glyphs(self):
        subject = build_subject({"us_holiday": False, "kr_holiday": False,
                                 "us_last_str": "10/07", "kr_last_str": "10/08"})
        self.assertIn("미국", subject)
        self.assertIn("한국", subject)
        self.assertNotIn("🇺🇸", subject)
        self.assertNotIn("🇰🇷", subject)

    def test_send_uses_related_images_and_saves_actual_preview(self):
        html = '<img src="cid:u">ETF'
        with tempfile.TemporaryDirectory() as directory:
            original = os.getcwd()
            try:
                os.chdir(directory)
                with patch.dict(os.environ, {"GMAIL_USER": "a@example.test",
                                             "GMAIL_APP_PASSWORD": "test-password",
                                             "RECIPIENT_EMAIL": "b@example.test"}):
                    with patch("src.main.smtplib.SMTP_SSL") as smtp:
                        send_email(html, "test")
                        sent = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
                        message = message_from_bytes(sent)
                        self.assertEqual(sum(p.get_content_type() == "image/png" for p in message.walk()), 2)
                        body = next(p for p in message.walk() if p.get_content_type()=="text/html")
                        self.assertEqual(body["Content-Transfer-Encoding"],"8bit")
                        self.assertEqual(body.get_payload(decode=True).decode("utf-8"),html)
                        self.assertEqual(smtp.return_value.__enter__.return_value.sendmail.call_args.kwargs["mail_options"],("BODY=8BITMIME",))
                        self.assertLessEqual(len(sent),95000)
                        self.assertLessEqual(max(map(len,sent.split(b"\r\n"))),998)
                        smtp.return_value.__enter__.return_value.sendmail.assert_called_once()
                        self.assertFalse(any(p.get_content_disposition() == "attachment" for p in message.walk()))
                        self.assertFalse(Path("work/email-full-report.html").exists())
                        preview = Path("work/email-preview.html").read_text(encoding="utf-8")
                        self.assertIn("data:image/png;base64,", preview)
                        self.assertNotIn("cid:", preview)
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
