"""Delivery tests: embedded flags, complete reports, and SMTP payload."""
import os
import tempfile
import unittest
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from src.main import compose_email_message, send_email, build_subject
from src.email_layout import MAX_BODY_BYTES


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

    def test_complete_report_attachment_has_self_contained_flags(self):
        html = '<img src="cid:ath-flag-kr">short'
        full = '<img src="cid:ath-flag-kr">all-stock-data'
        message = compose_email_message(html, "test", "sender@example.test", "reader@example.test", full)
        attachments = [part for part in message.walk() if part.get_content_disposition() == "attachment"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "ATH-full-report.html")
        report = attachments[0].get_payload(decode=True).decode("utf-8")
        self.assertIn("all-stock-data", report)
        self.assertIn("data:image/png;base64,", report)
        self.assertNotIn("cid:", report)

    def test_identical_complete_report_is_not_duplicated(self):
        message = compose_email_message("same", "test", "a@example.test", "b@example.test", "same")
        self.assertFalse(any(part.get_content_disposition() == "attachment" for part in message.walk()))

    def test_oversized_message_is_rejected_before_smtp(self):
        with self.assertRaises(ValueError):
            compose_email_message("가" * MAX_BODY_BYTES, "test", "a@example.test", "b@example.test")

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
                        send_email(html, "test", html)
                        sent = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
                        message = message_from_string(sent)
                        self.assertEqual(sum(p.get_content_type() == "image/png" for p in message.walk()), 2)
                        preview = Path("work/email-preview.html").read_text(encoding="utf-8")
                        self.assertIn("data:image/png;base64,", preview)
                        self.assertNotIn("cid:", preview)
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
