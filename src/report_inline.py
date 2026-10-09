"""Preserve the full US table as numbered, individually linked inline rows."""
import base64
import hashlib
import io
import json
import math
import re
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image
if __package__:
    from . import email_layout, email_flags
else:
    import email_layout, email_flags

MAX_HTML_BYTES = 60000
MAX_CANONICAL_BYTES = 65000

def digest(value):
    return hashlib.sha256(value).hexdigest()

def validate_delivery_size(html):
    size = len(html.encode("utf-8"))
    canonical = len(str(BeautifulSoup(html, "html5lib")).encode("utf-8"))
    if size > MAX_HTML_BYTES or canonical > MAX_CANONICAL_BYTES:
        raise RuntimeError(f"Display body {size:,}/{canonical:,} bytes exceeds the clipping budget; never remove candidates")
    return size, canonical

def safe_lines(html):
    html = re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                  lambda match: match[1] + match[2].replace("}", "}\n") + match[3],
                  html, flags=re.DOTALL)
    # Newlines are legal attribute separators, rather than extra visible text.
    return re.sub(r"<([A-Za-z][A-Za-z0-9]*)(?=[\s/>])", r"<\1\n", html)

def _number(cell, expected):
    value = cell.get_text(strip=True) if cell is not None else ""
    if not re.fullmatch(r"\d+", value) or int(value) != expected:
        raise RuntimeError("Report No. column is missing, reordered or incomplete")

def _table_numbers(doc):
    for table in doc.select("table.data-table"):
        for number, row in enumerate(table.select("tbody tr"), 1):
            cells = row.find_all("td", recursive=False)
            _number(cells[0] if cells else None, number)

def _source_rows(doc, expected):
    _table_numbers(doc)
    table = doc.find("table", id="us")
    if table is None:
        if expected["us"]:
            raise RuntimeError("US source table is missing")
        return []
    records = []
    for number, row in enumerate(table.select("tbody tr"), 1):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            raise RuntimeError("US source row is missing its No. or ticker")
        _number(cells[0], number)
        anchor = cells[2].find("a")
        ticker = str(anchor.contents[0]) if anchor and anchor.contents else ""
        url = anchor.get("href", "") if anchor else ""
        if not re.fullmatch(r"https://m\.stock\.naver\.com/worldstock/(?:stock|etf)/[A-Za-z0-9._-]+(?:/total)?", url):
            raise RuntimeError("Every US security must link to its Naver security page")
        records.append({"number": number, "ticker": ticker, "url": url})
    if [record["ticker"] for record in records] != expected["us"]:
        raise RuntimeError("US source rows do not match every collected candidate")
    return records

def _validate_rows(rows, records, height):
    if len(rows) != len(records):
        raise RuntimeError("Raster row inventory is incomplete")
    previous = None
    for row, record in zip(rows, records):
        if any(row.get(key) != record[key] for key in ("number", "ticker", "url")):
            raise RuntimeError("Raster No., ticker or Naver URL differs from the source")
        top, bottom = row.get("top"), row.get("bottom")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in (top, bottom)):
            raise RuntimeError("Invalid US row pixel geometry")
        if not 0 <= top < bottom <= height:
            raise RuntimeError("A US security lies outside the captured report")
        if previous is not None and abs(top - previous) > 1:
            raise RuntimeError("US row geometry has a gap or overlap")
        previous = bottom

def _font_size(geometry):
    value = geometry.get("font_size")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise RuntimeError("The captured US font size is missing or invalid")
    return float(value)

def _save(directory, delivery, meta):
    (directory / "email-delivery.html").write_text(delivery, encoding="utf-8")
    (directory / "inline-report.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")

def make_package(source, expected, png, rows, geometry, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    doc = BeautifulSoup(source, "html5lib")
    records = _source_rows(doc, expected)
    if not expected["us"]:
        if rows:
            raise RuntimeError("Unexpected raster rows in an empty-US report")
        validate_delivery_size(source)
        meta = {"source_sha256": digest(source.encode("utf-8")),
                "delivery_sha256": digest(source.encode("utf-8")),
                "us_tickers": [], "rows": [], "links": [], "geometry": {},
                "width": 0, "height": 0, "captured_font_size": None, "assets": []}
        _save(directory, source, meta)
        return source, meta
    table = doc.find("table", id="us")
    section = table.find_parent("div", class_="stock-section")
    if section is None:
        raise RuntimeError("US section is missing")
    full = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = full.size
    _validate_rows(rows, records, height)
    captured_font_size = _font_size(geometry)
    if width <= 0 or height <= 0 or len(records) > 997:
        raise RuntimeError("Inline report dimensions or row count exceeds the supported budget")

    # Integer, contiguous cuts retain every source pixel. Fractional CSS row
    # bounds may differ by less than one pixel, but row centres stay in their link.
    first = round(rows[0]["top"])
    cuts = [first] + [round(row["bottom"]) for row in rows]
    if first < 1 or any(a >= b for a, b in zip(cuts, cuts[1:])) or cuts[-1] > height:
        raise RuntimeError("US row image boundaries are invalid")
    spans = [{"kind": "header", "top": 0, "bottom": first}]
    for index, record in enumerate(records):
        span = {"kind": "row", "top": cuts[index], "bottom": cuts[index + 1], **record}
        if not span["top"] <= (rows[index]["top"] + rows[index]["bottom"]) / 2 < span["bottom"]:
            raise RuntimeError("US ticker is outside its linked row image")
        spans.append(span)
    if cuts[-1] < height:
        spans.append({"kind": "tail", "top": cuts[-1], "bottom": height})

    assets, links = [], []
    (directory / "report-inline").mkdir(exist_ok=True)
    replacement = doc.new_tag("div")
    replacement["class"] = ["section", "stock-section"]
    replacement["id"] = "us-display"
    replacement["aria-label"] = f"미국 ATH 후보 {len(records)}종목 전체"
    for index, span in enumerate(spans):
        cid = f"us-report-{index:03d}"
        relative = f"report-inline/{cid}.png"
        stream = io.BytesIO()
        full.crop((0, span["top"], width, span["bottom"])).save(
            stream, format="PNG", optimize=True)
        payload = stream.getvalue()
        (directory / relative).write_bytes(payload)
        asset = {**span, "cid": cid, "path": relative, "sha256": digest(payload),
                 "width": width, "height": span["bottom"] - span["top"]}
        assets.append(asset)
        image = doc.new_tag("img", src="cid:" + cid)
        image["width"], image["height"] = str(width), str(asset["height"])
        if span["kind"] == "row":
            image["alt"] = f'{span["number"]}. {span["ticker"]}'
            anchor = doc.new_tag("a", href=span["url"])
            anchor.append(image)
            replacement.append(anchor)
            links.append({key: asset[key] for key in ("number", "ticker", "url", "cid")})
        else:
            image["alt"] = "미국 ATH 후보 표 머리글" if span["kind"] == "header" else ""
            replacement.append(image)

    # Shared rules avoid repeating long inline styles for 218 linked rows.
    style = doc.new_tag("style")
    style.string = (f"#us-display a{{display:block;width:{width}px;line-height:0}}"
                    f"#us-display img{{display:block;width:{width}px;max-width:none;"
                    "height:auto;border:0;margin:0;padding:0}")
    doc.head.append(style)
    section.replace_with(replacement)
    delivery = safe_lines(str(doc))
    validate_delivery_size(delivery)
    if max((len(line.encode("utf-8")) for line in delivery.replace("\r\n", "\n").split("\n")), default=0) > 998:
        raise RuntimeError("Inline report exceeds the SMTP line limit")
    meta = {"source_sha256": digest(source.encode("utf-8")),
            "delivery_sha256": digest(delivery.encode("utf-8")),
            "us_tickers": expected["us"], "rows": rows, "links": links,
            "geometry": geometry, "width": width, "height": height,
            "captured_font_size": captured_font_size, "pixels_sha256": digest(full.tobytes()), "assets": assets}
    _save(directory, delivery, meta)
    return delivery, meta

def verify_package(source, delivery, expected, meta, directory):
    directory = Path(directory).resolve()
    if (meta.get("source_sha256") != digest(source.encode("utf-8")) or
            meta.get("delivery_sha256") != digest(delivery.encode("utf-8"))):
        raise RuntimeError("Inline report does not match the verified source")
    records = _source_rows(BeautifulSoup(source, "html5lib"), expected)
    if meta.get("us_tickers") != expected["us"]:
        raise RuntimeError("Inline report is missing US candidates")
    _validate_rows(meta.get("rows", []), records, meta.get("height", 0))
    if records and meta.get("captured_font_size") != _font_size(meta.get("geometry", {})):
        raise RuntimeError("The captured US font size changed after browser validation")
    actual = email_layout.inventory(delivery)
    if actual != {**expected, "us": []}:
        raise RuntimeError("Non-US tables changed during inline packaging")
    validate_delivery_size(delivery)
    doc = BeautifulSoup(delivery, "html5lib")
    _table_numbers(doc)
    container = doc.find(id="us-display")
    images = container.find_all("img") if container else []
    assets = meta.get("assets", [])
    if not records and not assets and not images and not meta.get("links"):
        return {}
    if (not assets or not container or
            [image.get("src") for image in images] != ["cid:" + asset["cid"] for asset in assets]):
        raise RuntimeError("Inline report images are missing or out of order")
    row_assets = [asset for asset in assets if asset.get("kind") == "row"]
    wanted_links = [{**record, "cid": asset["cid"]} for record, asset in zip(records, row_assets)]
    if len(row_assets) != len(records) or meta.get("links") != wanted_links:
        raise RuntimeError("Inline report Naver links are missing, reordered or changed")
    anchors = container.find_all("a")
    if len(anchors) != len(records):
        raise RuntimeError("US securities lack individually clickable Naver links")
    for anchor, record, asset in zip(anchors, records, row_assets):
        picture = anchor.find("img", recursive=False)
        if (any(asset.get(key) != record[key] for key in ("number", "ticker", "url")) or
                anchor.get("href") != record["url"] or picture is None or
                picture.get("src") != "cid:" + asset["cid"] or
                picture.get("alt") != f'{record["number"]}. {record["ticker"]}'):
            raise RuntimeError("A clickable US row differs from its No., ticker or Naver URL")
    canvas = Image.new("RGB", (meta["width"], meta["height"]))
    payloads, cursor = {}, 0
    for index, (asset, image) in enumerate(zip(assets, images)):
        cid = f"us-report-{index:03d}"
        relative = f"report-inline/{cid}.png"
        path = (directory / asset["path"]).resolve()
        if (not path.is_relative_to(directory) or asset["cid"] != cid or asset["path"] != relative or
                int(image.get("width", 0)) != meta["width"] or
                int(image.get("height", 0)) != asset["height"]):
            raise RuntimeError("Invalid inline report asset path or display dimensions")
        payload = path.read_bytes()
        picture = Image.open(io.BytesIO(payload)).convert("RGB")
        if (digest(payload) != asset["sha256"] or
                picture.size != (meta["width"], asset["height"]) or asset["width"] != meta["width"]):
            raise RuntimeError("Inline report image changed after browser validation")
        if asset["top"] != cursor or asset["bottom"] != cursor + asset["height"]:
            raise RuntimeError("Inline report has a missing or overlapping image segment")
        canvas.paste(picture, (0, cursor))
        cursor = asset["bottom"]
        payloads[cid] = payload
    if cursor != meta["height"] or digest(canvas.tobytes()) != meta["pixels_sha256"]:
        raise RuntimeError("Inline report pixels are incomplete")
    for row, asset in zip(meta["rows"], row_assets):
        center = (row["top"] + row["bottom"]) / 2
        if not asset["top"] <= center < asset["bottom"]:
            raise RuntimeError("A US security is outside its clickable row")
    return payloads

def inline_sources(html, payloads):
    html = email_flags.inline_flag_sources(html)
    for cid, payload in payloads.items():
        html = html.replace("cid:" + cid, "data:image/png;base64," + base64.b64encode(payload).decode("ascii"))
    return html

def plain_report(source):
    doc = BeautifulSoup(source, "html5lib")
    return doc.body.get_text(" ", strip=True)
