"""Delivery regressions: every candidate in one body and zero attachments."""
import os
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from src.main import compose_email_message, send_email, build_subject, main
from tools.preview_email import sample_data, make_stock
from datetime import date
import re


class EmailDeliveryTests(unittest.TestCase):
    def test_inline_cid_flags_have_matching_png_parts(self):
        html = '<img src="cid:ath-flag-us"><img src="cid:ath-flag-kr"><h1>ETF</h1>'
        message = compose_email_message(html, "test", "sender@example.test", "reader@example.test")
        parts = list(message.walk())
        images = [part for part in parts if part.get_content_type() == "image/png"]
        self.assertEqual({part["Content-ID"] for part in images}, {"<ath-flag-us>", "<ath-flag-kr>"})
        self.assertEqual(len(images), 2)
        self.assertTrue(any(part.get_content_type() == "multipart/related" for part in parts))
        for part in images:
            self.assertEqual(part.get_content_disposition(), "inline")
            self.assertTrue(part.get_payload(decode=True).startswith(b"\x89PNG\r\n\x1a\n"))
        body = [part for part in parts if part.get_content_type() == "text/html"][0]
        self.assertEqual(body.get_payload(decode=True).decode("utf-8"), html)
        self.assertTrue(any(part.get_content_type() == "text/plain" for part in parts))

    def test_complete_large_html_is_allowed_with_no_attachment(self):
        html = '<img src="cid:ath-flag-us">' + "가" * 85000
        message = compose_email_message(html, "test", "a@example.test", "b@example.test")
        self.assertEqual(message.get_content_type(), "multipart/related")
        self.assertFalse(any(part.get_content_disposition() == "attachment" for part in message.walk()))
        bodies = [part for part in message.walk() if part.get_content_type() == "text/html"]
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0].get_payload(decode=True).decode("utf-8"), html)

    def test_main_sends_all_218_us_and_17_kr_candidates_once(self):
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
        keys = re.findall(r'class="stock-row" data-key="([^"]+)"', html)
        self.assertEqual(keys, ["KR:" + r["ticker"] for r in data["kr"]] + ["US:" + r["ticker"] for r in data["us"]])
        self.assertEqual(sum(key.startswith("US:") for key in keys), 218)
        self.assertEqual(sum(key.startswith("KR:") for key in keys), 17)
        self.assertNotIn("첨부", html)

    def test_subject_uses_country_names_instead_of_flag_letter_glyphs(self):
        subject = build_subject({"us_holiday": False, "kr_holiday": False,
                                 "us_last_str": "10/07", "kr_last_str": "10/08"})
        self.assertIn("미국", subject)
        self.assertIn("한국", subject)
        self.assertNotIn("🇺🇸", subject)
        self.assertNotIn("🇰🇷", subject)

    def test_send_uses_related_images_and_saves_actual_preview(self):
        html = '<img src="cid:ath-flag-us">ETF'
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
                        message = message_from_string(sent)
                        self.assertEqual(sum(p.get_content_type() == "image/png" for p in message.walk()), 2)
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
