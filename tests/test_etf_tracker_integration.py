import hashlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.main import main
from src.etf_history import validate_snapshot
from tools.preview_email import sample_data


class TrackerExportIntegrationTests(unittest.TestCase):
    def test_prepare_exports_the_exact_report_inventory_without_sending(self):
        data = sample_data()
        candidates = data["etf_info"]["rows"][:4]
        us = [r for r in candidates if r["market"] == "US"]
        kr = [r for r in candidates if r["market"] != "US"]

        def collect_us(usd_krw, comparison, **kwargs):
            comparison.extend(candidates)
            return us

        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with ExitStack() as patches:
                    values = {"get_trading_info": data["info"], "get_usd_krw": data["usd_krw"],
                              "get_market_indices": data["indices"], "get_kr_ath": kr,
                              "load_snapshots": {"US": {}, "KR": {}}, "compute_new_tickers": []}
                    for name, value in values.items():
                        patches.enter_context(patch("src.main." + name, return_value=value))
                    patches.enter_context(patch("src.main.get_us_ath", side_effect=collect_us))
                    patches.enter_context(patch("src.main.synchronize_etf_market_dates"))
                    send = patches.enter_context(patch("src.main.send_email"))
                    smtp = patches.enter_context(patch("src.main.smtplib.SMTP_SSL"))
                    save = patches.enter_context(patch("src.main.save_snapshots"))
                    main(prepare_only=True)
                    send.assert_not_called()
                    smtp.assert_not_called()
                    save.assert_not_called()
                snapshot = validate_snapshot(json.loads(Path("work/etf-tracker-snapshot.json").read_text(encoding="utf-8")))
                proof = json.loads(Path("work/market-date-proof.json").read_text(encoding="utf-8"))
                body = Path("work/email-body.html").read_text(encoding="utf-8")
                self.assertEqual(snapshot["body_sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())
                original = {r["country"] + ":" + r["ticker"]: r for r in proof["etfs"] if r["in_comparison_universe"]}
                self.assertEqual({r["id"] for r in snapshot["rows"]}, set(original))
                names = {r["ticker"]: r["name"] for r in candidates}
                for row in snapshot["rows"]:
                    self.assertEqual(row["cagr"], original[row["id"]]["lifetime_cagr"])
                    self.assertEqual(row["price_end_date"], original[row["id"]]["price_end_date"])
                    self.assertEqual(row["name"], names[row["ticker"]])
            finally:
                os.chdir(previous)
