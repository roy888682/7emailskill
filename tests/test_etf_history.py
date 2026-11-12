import copy
import hashlib
import json
import math
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.etf_history import (build_site_data, make_snapshot, save_snapshot,
                             snapshot_from_audit, validate_snapshot)


def example_proof():
    def row(country, ticker, first="2020-01-02", last="2026-11-11", growth=2.3456789012345):
        years = (date.fromisoformat(last) - date.fromisoformat(first)).days / 365.25
        return {"country": country, "ticker": ticker, "name": "Fixture " + ticker,
                "in_comparison_universe": True, "requested_market_date": "2026-11-11",
                "price_start_date": first, "price_end_date": last,
                "initial_adjusted_price": .2051851749420166,
                "latest_adjusted_price": .2051851749420166 * growth,
                "lifetime_cagr": math.expm1(math.log(growth) / years) * 100, "lifetime_years": years,
                "date_status": "market_close" if last == "2026-11-11" else "latest_available",
                "price_basis": "Fixture same-basis prices", "price_currency": "USD" if country == "US" else "KRW"}
    rows = [row("US", "ETF"), row("KR", "000001", last="2026-11-10"),
            row("KR", "YOUNG", first="2026-01-01")]
    unavailable = row("US", "MISSING")
    for key in ("price_start_date", "price_end_date", "initial_adjusted_price", "latest_adjusted_price", "lifetime_cagr", "lifetime_years"):
        unavailable[key] = None
    unavailable["date_status"] = "unavailable"
    rows.append(unavailable)
    return {"version": 3, "market_dates": {"US": "2026-11-11", "KR": "2026-11-11"},
            "etfs": rows, "counts": {"US": 2, "KR": 2},
            "comparison_universe": [r["country"] + ":" + r["ticker"] for r in rows]}


class ETFHistoryTests(unittest.TestCase):
    def snapshot(self, **kwargs):
        return make_snapshot(example_proof(), collected_at="2026-11-12T00:20:00Z", **kwargs)

    def test_preserves_exact_report_values_and_korean_collection_day(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["date"], "2026-11-12")
        self.assertEqual(snapshot["collected_at"], "2026-11-12T09:20:00+09:00")
        original = example_proof()["etfs"][0]
        row = next(row for row in snapshot["rows"] if row["id"] == "US:ETF")
        self.assertEqual(row["cagr"], original["lifetime_cagr"])
        self.assertEqual(row["initial_price"], original["initial_adjusted_price"])
        self.assertNotEqual(row["cagr"], round(row["cagr"], 1))
        self.assertEqual(validate_snapshot(json.loads(json.dumps(snapshot))), snapshot)

    def test_full_inventory_keeps_young_unavailable_and_non_ath_candidates(self):
        rows = {r["ticker"]: r for r in self.snapshot()["rows"]}
        self.assertFalse(rows["YOUNG"]["eligible"])
        self.assertIsNotNone(rows["YOUNG"]["cagr"])
        self.assertFalse(rows["MISSING"]["eligible"])
        self.assertIsNone(rows["MISSING"]["cagr"])
        self.assertTrue(rows["ETF"]["eligible"])
        self.assertEqual(rows["000001"]["status"], "latest_available")
        self.assertEqual(rows["000001"]["price_end_date"], "2026-11-10")

    def test_incorrect_returns_prices_dates_and_inventory_fail_closed(self):
        changes = [lambda p: p["etfs"][0].update(lifetime_cagr=99),
                   lambda p: p["etfs"][0].update(lifetime_years=7),
                   lambda p: p["etfs"][0].update(initial_adjusted_price=True),
                   lambda p: p["etfs"][0].update(latest_adjusted_price=float("nan")),
                   lambda p: p["etfs"][0].update(price_end_date="2026-11-13"),
                   lambda p: p["etfs"][0].update(date_status="latest_available"),
                   lambda p: p["etfs"][-1].update(lifetime_cagr=0),
                   lambda p: p["counts"].update(US=3),
                   lambda p: p["comparison_universe"].pop(),
                   lambda p: p["etfs"].append(copy.deepcopy(p["etfs"][0]))]
        for change in changes:
            with self.subTest(change=change):
                proof = example_proof()
                change(proof)
                with self.assertRaises((ValueError, KeyError)):
                    make_snapshot(proof, collected_at="2026-11-12T09:30:00+09:00")

    def test_exact_one_year_rule_uses_days_over_365_point_25(self):
        proof = example_proof()
        row = proof["etfs"][0]
        for first, expected in (("2025-11-11", False), ("2025-11-10", True)):
            row["price_start_date"] = first
            row["lifetime_years"] = (date(2026, 11, 11) - date.fromisoformat(first)).days / 365.25
            row["lifetime_cagr"] = math.expm1(math.log(row["latest_adjusted_price"] / row["initial_adjusted_price"]) / row["lifetime_years"]) * 100
            snap = make_snapshot(proof, collected_at="2026-11-12T09:00:00+09:00")
            self.assertEqual(next(r for r in snap["rows"] if r["id"] == "US:ETF")["eligible"], expected)

    def test_same_day_updates_are_idempotent_and_older_runs_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot()
            self.assertTrue(save_snapshot(snapshot, directory))
            self.assertFalse(save_snapshot(snapshot, directory))
            earlier = copy.deepcopy(snapshot)
            earlier["collected_at"] = "2026-11-12T08:00:00+09:00"
            self.assertFalse(save_snapshot(earlier, directory))
            newer = copy.deepcopy(snapshot)
            newer["collected_at"] = "2026-11-12T10:00:00+09:00"
            self.assertTrue(save_snapshot(newer, directory))
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 1)
            self.assertEqual(json.loads((Path(directory) / "2026-11-12.json").read_text(encoding="utf-8")), newer)

    def test_snapshot_eligibility_identity_and_collection_date_cannot_be_forged(self):
        for key, value in (("eligible", True), ("id", "KR:FORGED")):
            snapshot = self.snapshot()
            next(r for r in snapshot["rows"] if r["ticker"] == "MISSING")[key] = value
            with self.assertRaises(ValueError):
                validate_snapshot(snapshot)
        snapshot = self.snapshot()
        snapshot["date"] = "2026-11-11"
        with self.assertRaises(ValueError):
            validate_snapshot(snapshot)

    def test_recovery_requires_matching_body_inventory_hashes_and_ranking(self):
        proof = example_proof()
        body = b"<html>actual test report body</html>"
        manifest = {"us": [], "kr": [], "new": [], "etf": ["ETF", "000001"]}
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        proof.update(body_sha256=hashlib.sha256(body).hexdigest(), manifest_sha256=hashlib.sha256(canonical).hexdigest())
        args = (json.dumps(proof).encode(), body, json.dumps(manifest).encode(), "2026-11-12T09:00:00+09:00", {"kind": "test"})
        self.assertEqual(len(snapshot_from_audit(*args)["rows"]), 4)
        with self.assertRaises(ValueError):
            snapshot_from_audit(args[0], b"changed", *args[2:])
        manifest["etf"].append("YOUNG")
        proof["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaises(ValueError):
            snapshot_from_audit(json.dumps(proof).encode(), body, json.dumps(manifest).encode(), *args[3:])

    def test_monthly_shards_align_missing_candidates_and_keep_exact_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.snapshot()
            save_snapshot(snapshot, root / "history")
            next_month = copy.deepcopy(snapshot)
            next_month.update(date="2026-12-01", collected_at="2026-12-01T09:00:00+09:00")
            next_month["rows"] = [r for r in next_month["rows"] if r["ticker"] != "YOUNG"]
            save_snapshot(next_month, root / "history")
            index = build_site_data(root / "history", root / "site")
            self.assertEqual(index["months"], ["2026-11", "2026-12"])
            self.assertEqual(index["dates"], ["2026-11-12", "2026-12-01"])
            november = json.loads((root / "site/history/2026-11.json").read_text(encoding="utf-8"))
            self.assertEqual(november["series"]["US:ETF"][0][0], example_proof()["etfs"][0]["lifetime_cagr"])
            self.assertEqual(len(index["etfs"]), 4)
            self.assertEqual(next(r for r in index["etfs"] if r["ticker"] == "YOUNG")["last_observed_date"], "2026-11-12")

    def test_empty_history_builds_an_honest_empty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            index = build_site_data(Path(directory) / "history", Path(directory) / "site")
            self.assertEqual(index["etfs"], [])
            self.assertEqual(index["dates"], [])
            self.assertIsNone(index["updated_at"])


if __name__ == "__main__":
    unittest.main()
