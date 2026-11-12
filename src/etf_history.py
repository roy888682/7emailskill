"""Durable observations of the report's lifetime CAGR, without price backfilling.

This module intentionally uses only the standard library. Historical observations
are what was collected on that date, not today's recalculation of old prices.
"""
import calendar
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SCHEMA = 1
SOURCE_REPOSITORY = "https://github.com/roy888682/7emailskill"
POINT_FIELDS = ["cagr", "price_end_date", "status", "eligible"]


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"Invalid ISO date: {value!r}")
    return value


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Collection time must include a time zone")
    return result.astimezone(KST)


def make_snapshot(proof, candidates=(), collected_at=None, source=None):
    """Copy and independently verify every comparison candidate from a v3 audit."""
    if proof.get("version") != 3:
        raise ValueError("A version-3 market-date proof is required")
    collected = _timestamp(collected_at) if collected_at else datetime.now(KST)
    anchors = {country: _date(proof["market_dates"][country]) for country in ("US", "KR")}
    if any(value > collected.date().isoformat() for value in anchors.values()):
        raise ValueError("Market date is later than collection date")
    names = {}
    for row in candidates:
        country = row.get("country") or ("US" if row.get("market") == "US" else "KR")
        names[(country, str(row.get("ticker")))] = row
    counts = {country: 0 for country in anchors}
    seen, rows, members = set(), [], []
    for row in proof["etfs"]:
        country, ticker = row["country"], str(row["ticker"])
        identity = country + ":" + ticker
        if country not in anchors or not ticker or identity in seen:
            raise ValueError("Missing or duplicate ETF identity")
        seen.add(identity)
        counts[country] += 1
        if type(row.get("in_comparison_universe")) is not bool:
            raise ValueError("Missing comparison membership")
        if not row["in_comparison_universe"]:
            continue
        members.append(identity)
        anchor = anchors[country]
        if row.get("requested_market_date") != anchor:
            raise ValueError(f"Market date mismatch: {identity}")
        initial, latest = row.get("initial_adjusted_price"), row.get("latest_adjusted_price")
        first, last = row.get("price_start_date"), row.get("price_end_date")
        cagr, years = row.get("lifetime_cagr"), row.get("lifetime_years")
        status = row.get("date_status")
        if status == "unavailable":
            if any(value is not None for value in (initial, latest, first, last, cagr, years)):
                raise ValueError(f"Unavailable ETF contains prices/returns: {identity}")
            eligible = False
        else:
            _date(first)
            _date(last)
            if not first < last <= anchor:
                raise ValueError(f"Invalid price interval: {identity}")
            if not all(_number(value) for value in (initial, latest, cagr, years)) or min(initial, latest) <= 0:
                raise ValueError(f"Invalid price or CAGR: {identity}")
            actual_years = (date.fromisoformat(last) - date.fromisoformat(first)).days / 365.25
            expected = math.expm1(math.log(latest / initial) / actual_years) * 100
            if not math.isclose(years, actual_years, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"Incorrect elapsed years: {identity}")
            if not math.isclose(cagr, expected, rel_tol=1e-10, abs_tol=1e-8):
                raise ValueError(f"CAGR differs from exact dated prices: {identity}")
            if status != ("market_close" if last == anchor else "latest_available"):
                raise ValueError(f"Incorrect fallback status: {identity}")
            if not row.get("price_basis") or not row.get("price_currency"):
                raise ValueError(f"Missing price basis/currency: {identity}")
            eligible = actual_years >= 1
        info = names.get((country, ticker), row)
        rows.append({"id": identity, "country": country, "ticker": ticker,
                     "name": str(info.get("name") or ticker),
                     "investment_area": str(info.get("investment_area") or info.get("industry") or ""),
                     "management_style": row.get("management_style") or "미확인",
                     "market_date": anchor, "price_start_date": first, "price_end_date": last,
                     "initial_price": initial, "latest_price": latest, "cagr": cagr,
                     "lifetime_years": years, "status": status, "eligible": eligible,
                     "price_basis": row.get("price_basis"), "currency": row.get("price_currency")})
    if counts != proof.get("counts"):
        raise ValueError("ETF inventory counts do not match the proof")
    if sorted(members) != sorted(proof.get("comparison_universe", [])) or not rows:
        raise ValueError("ETF comparison inventory is incomplete or empty")
    return {"schema_version": SCHEMA, "metric": "lifetime_cagr_365.25",
            "date": collected.date().isoformat(), "collected_at": collected.isoformat(),
            "market_dates": anchors, "source": source or {"kind": "prepared_report"},
            "body_sha256": proof.get("body_sha256"),
            "rows": sorted(rows, key=lambda row: row["id"])}


def snapshot_from_audit(proof_bytes, html_bytes, manifest_bytes, collected_at, source):
    """Recover only real report audits bound to their exact HTML and inventory."""
    proof, manifest = json.loads(proof_bytes), json.loads(manifest_bytes)
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if proof.get("body_sha256") != hashlib.sha256(html_bytes).hexdigest():
        raise ValueError("Recovered report body hash mismatch")
    if proof.get("manifest_sha256") != hashlib.sha256(canonical).hexdigest():
        raise ValueError("Recovered report inventory hash mismatch")
    snapshot = make_snapshot(proof, collected_at=collected_at, source=source)
    expected = sorted(row["ticker"] for row in snapshot["rows"] if row["eligible"])
    if sorted(manifest.get("etf", [])) != expected:
        raise ValueError("Recovered ranking differs from comparison inventory")
    return snapshot


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def validate_snapshot(snapshot):
    """Validate saved/exported records too, not just their originating audit."""
    if snapshot.get("schema_version") != SCHEMA or snapshot.get("metric") != "lifetime_cagr_365.25":
        raise ValueError("Unsupported snapshot schema/metric")
    if snapshot["date"] != _timestamp(snapshot["collected_at"]).date().isoformat():
        raise ValueError("Snapshot date must be the Korean collection date")
    rows = []
    for row in snapshot["rows"]:
        if row["id"] != row["country"] + ":" + row["ticker"]:
            raise ValueError("Snapshot identity mismatch")
        rows.append({**row, "asset_type": "ETF", "in_comparison_universe": True,
                     "requested_market_date": row["market_date"], "date_status": row["status"],
                     "initial_adjusted_price": row["initial_price"], "latest_adjusted_price": row["latest_price"],
                     "lifetime_cagr": row["cagr"], "price_currency": row["currency"]})
    proof = {"version": 3, "market_dates": snapshot["market_dates"], "etfs": rows,
             "counts": {country: sum(row["country"] == country for row in rows) for country in ("US", "KR")},
             "comparison_universe": [row["id"] for row in snapshot["rows"]]}
    checked = make_snapshot(proof, collected_at=snapshot["collected_at"])
    if any(a["eligible"] is not b.get("eligible") for a, b in zip(checked["rows"], sorted(snapshot["rows"], key=lambda r: r["id"]))):
        raise ValueError("Snapshot eligibility does not match exact years")
    return snapshot


def save_snapshot(snapshot, directory):
    validate_snapshot(snapshot)
    path = Path(directory) / (snapshot["date"] + ".json")
    if path.exists():
        existing = validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
        if _timestamp(existing["collected_at"]) >= _timestamp(snapshot["collected_at"]):
            return False
    return write_json(path, snapshot)


def build_site_data(history_directory, output_directory):
    """Build monthly shards, so no single ever-growing JSON exceeds GitHub limits."""
    directory = Path(output_directory)
    snapshots = [validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
                 for path in sorted(Path(history_directory).glob("????-??-??.json"))]
    catalog, months = {}, {}
    for snapshot in snapshots:
        month = snapshot["date"][:7]
        shard = months.setdefault(month, {"schema_version": SCHEMA, "dates": [], "series": {}})
        shard["dates"].append(snapshot["date"])
        for row in snapshot["rows"]:
            previous_name = catalog.get(row["id"], {}).get("name")
            current = {**row, "last_observed_date": snapshot["date"]}
            if current["name"] == current["ticker"] and previous_name:
                current["name"] = previous_name
            catalog[row["id"]] = current
            shard["series"].setdefault(row["id"], {})[snapshot["date"]] = [
                row["cagr"], row["price_end_date"], row["status"], row["eligible"]]
    for month, shard in months.items():
        shard["series"] = {key: [points.get(day) for day in shard["dates"]]
                            for key, points in sorted(shard["series"].items())}
        write_json(directory / "history" / (month + ".json"), shard)
    latest = snapshots[-1] if snapshots else None
    index = {"schema_version": SCHEMA, "metric": "lifetime_cagr_365.25", "timezone": "Asia/Seoul",
             "source_repository": SOURCE_REPOSITORY, "point_fields": POINT_FIELDS,
             "dates": [s["date"] for s in snapshots], "months": sorted(months),
             "updated_at": latest["collected_at"] if latest else None,
             "market_dates": latest["market_dates"] if latest else {},
             "etfs": sorted(catalog.values(), key=lambda row: row["id"])}
    write_json(directory / "index.json", index)
    return index
