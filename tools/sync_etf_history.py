#!/usr/bin/env python3
"""Import actual report artifacts, persist daily observations, rebuild static data."""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.etf_history import (KST, build_site_data, make_snapshot, save_snapshot,
                             snapshot_from_audit, validate_snapshot)

ROOT = Path(__file__).resolve().parents[1]
REPO = "roy888682/7emailskill"


class ArtifactRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if redirected is not None and urllib.parse.urlparse(request.full_url).netloc != urllib.parse.urlparse(url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def github_get(path, binary=False):
    if not path.startswith(f"https://api.github.com/repos/{REPO}/"):
        raise ValueError("Only this repository's Actions API is allowed")
    request = urllib.request.Request(path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "7emailskill-etf-history",
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "X-GitHub-Api-Version": "2022-11-28"})
    for attempt in range(3):
        try:
            with urllib.request.build_opener(ArtifactRedirectHandler()).open(request, timeout=60) as response:
                raw = response.read()
            return raw if binary else json.loads(raw)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def import_github(history):
    """Read only main-branch production mail runs; never import test fixtures."""
    base = f"https://api.github.com/repos/{REPO}/actions"
    runs = github_get(base + "/workflows/daily_ath_email.yml/runs?branch=main&per_page=30")["workflow_runs"]
    imported = 0
    for run in reversed(runs):
        if (run["head_branch"] != "main" or run["status"] != "completed"
                or run.get("path") != ".github/workflows/daily_ath_email.yml"):
            continue
        artifacts = github_get(base + f"/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
        for artifact in artifacts:
            is_export = artifact["name"].startswith("etf-observation-")
            is_audit = artifact["name"].startswith("email-delivery-diagnostics-")
            if artifact["expired"] or not (is_export or is_audit):
                continue
            source = {"kind": "report_export" if is_export else "recovered_report_audit",
                      "run_id": run["id"], "commit": run["head_sha"], "url": run["html_url"]}
            with zipfile.ZipFile(io.BytesIO(github_get(artifact["archive_download_url"], binary=True))) as archive:
                files = {Path(name).name: name for name in archive.namelist()}
                if is_export and "etf-tracker-snapshot.json" in files:
                    snapshot = validate_snapshot(json.loads(archive.read(files["etf-tracker-snapshot.json"])))
                    snapshot["source"] = source
                elif is_audit and all(name in files for name in ("market-date-proof.json", "email-body.html", "report-manifest.json")):
                    try:
                        snapshot = snapshot_from_audit(
                            archive.read(files["market-date-proof.json"]), archive.read(files["email-body.html"]),
                            archive.read(files["report-manifest.json"]), run["run_started_at"], source)
                    except (ValueError, KeyError, OverflowError) as error:
                        print(f"Skip incompatible historical audit {run['id']}: {error}")
                        continue
                else:
                    continue
            imported += int(save_snapshot(snapshot, history))
    print(f"Imported/updated {imported} actual daily report observations")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--github", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    history = args.root / "data" / "etf-history"
    if args.github:
        import_github(history)
    if args.snapshot:
        save_snapshot(json.loads(args.snapshot.read_text(encoding="utf-8")), history)
    index = build_site_data(history, args.root / "dashboard" / "data")
    today = datetime.now(KST).date().isoformat()
    need = not index["dates"] or index["dates"][-1] != today
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"need_collection={str(need).lower()}\n")
    print(json.dumps({"days": len(index["dates"]), "etfs": len(index["etfs"]),
                      "latest_collection": index["updated_at"], "need_collection": need}, ensure_ascii=False))


if __name__ == "__main__":
    main()
