"""Compact native email tables without changing their text, links or typography."""
import hashlib
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString
if __package__:
    from . import email_layout
else:
    import email_layout

MAX_HTML_BYTES = 75000
MAX_CANONICAL_BYTES = 90000
MAX_STYLE_CHARACTERS = 8192

def validate_source_size(html):
    size = len(html.encode("utf-8"))
    if size > 200000:
        raise RuntimeError("Source body exceeds preparation budget; never remove candidates")
    return size

def digest(value):
    return hashlib.sha256(value).hexdigest()

def validate_delivery_size(html):
    doc = BeautifulSoup(html, "html5lib")
    size = len(html.encode("utf-8"))
    canonical = len(str(doc).encode("utf-8"))
    style_size = sum(len(str(tag.string or "")) for tag in doc.find_all("style"))
    if size > MAX_HTML_BYTES or canonical > MAX_CANONICAL_BYTES:
        raise RuntimeError(f"Native body {size:,}/{canonical:,} bytes exceeds the clipping budget; never remove candidates")
    if style_size >= MAX_STYLE_CHARACTERS:
        raise RuntimeError("Native CSS exceeds Gmail's style budget; never remove candidates")
    return size, canonical

def _selectors(prefixes, column):
    return ",".join(prefix + " " + "+".join(["td"] * column) for prefix in prefixes)

def _column_css():
    # Gmail desktop supports adjacent-sibling selectors, but not nth-child.
    # Each rule intentionally also matches later cells; later, more specific
    # thresholds restore the next column's exact original style.
    groups = []
    stocks = (".c",)
    rules = (
        (1, "text-align:right;font-variant-numeric:tabular-nums"),
        (2, "text-align:center;font-variant-numeric:normal"),
        (3, "text-align:left"),
        (6, "text-align:right;font-variant-numeric:tabular-nums"),
        (7, "color:#c23932"),
        (8, "text-align:left;font-variant-numeric:normal;color:#17263d"),
        (9, "text-align:right;font-variant-numeric:tabular-nums;color:#c23932"),
        (10, "color:#17263d"),
        (11, "text-align:left;font-variant-numeric:normal"),
    )
    for column, declarations in rules:
        groups.append(_selectors(stocks, column) + "{" + declarations + "}")
    etfs = (".v",)
    rules = (
        (1, "text-align:right;font-variant-numeric:tabular-nums"),
        (2, "text-align:center;font-variant-numeric:normal"),
        (3, "text-align:left"),
        (5, "text-align:right;font-variant-numeric:tabular-nums;background:#eaf1fb;font-weight:bold;color:#c23932"),
        (6, "background:transparent;font-weight:normal;color:#245ba6"),
        (7, "color:#087d67"),
        (8, "color:#7944b0"),
        (9, "color:#17263d"),
        (11, "text-align:left;font-variant-numeric:normal;font-size:9.5px"),
    )
    for column, declarations in rules:
        groups.append(_selectors(etfs, column) + "{" + declarations + "}")
    return "".join(groups)

def _numbers(doc):
    for table in doc.select("table.data-table"):
        heading = table.select_one("thead th")
        if heading is None or heading.get_text(strip=True) != "No.":
            raise RuntimeError("A native table is missing its No. heading")
        for number, row in enumerate(table.select("tbody tr"), 1):
            cells = row.find_all("td", recursive=False)
            if not cells or cells[0].get_text(strip=True) != str(number):
                raise RuntimeError("Native No. values are missing, reordered or incomplete")

def _semantic_node(node):
    if isinstance(node, NavigableString):
        return str(node)
    attrs = {key: value for key, value in node.attrs.items() if key != "class"}
    return [node.name, attrs, [_semantic_node(child) for child in node.children]]

def semantic_digest(doc):
    payload = json.dumps(_semantic_node(doc.body), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return digest(payload.encode("utf-8"))

def _trim_css(css, doc):
    # Only rules whose targets are absent, or whose identical replacement is
    # supplied below, are removed. The accepted source stylesheet stays intact.
    unused = (".hero .eyebrow", ".metric-label", ".etf-details", ".etf-details h3",
              ".report-note", ".data-table .y", ".data-table .d", ".r",
              ".data-table .p1", ".data-table .p3", ".data-table .p5", ".data-table .p10")
    if not doc.select(".notice"):
        unused += (".notice",)
    css = re.sub(r"([^{}]+)\{([^{}]*)\}",
                 lambda match: "" if match[1].strip() in unused else match[0], css)
    css = css.replace(".f img{", ".data-table img{")
    css = css.replace(".m{", ".etf-comparison b{")
    css = css.replace(".data-table .t,.data-table a{", ".data-table a{")
    css = css.replace(".data-table .n,.data-table .r{", ".data-table .n{")
    css = css.replace(".asset,.e,.s,", "")
    css = css.replace(".s,.stock-table b", ".stock-table b")
    css = css.replace(".e,.stock-table i", ".stock-table i")
    # All visible content is inside .shell, which already repeats these body
    # font/color declarations; removing the redundant declarations changes no
    # descendant's computed style.
    css = re.sub(r"body\{[^}]*\}", "body{margin:0;background:#f2f5f8}", css, count=1)
    return css

def _transport(source):
    source = re.sub(r">\s+<", "><", source).strip()
    source = re.sub(r"</td>(?=<(?:td|th|/tr))", "", source)
    source = re.sub(r"</th>(?=<(?:td|th|/tr))", "", source)
    source = re.sub(r"</tr>(?=<(?:tr|/thead|/tbody|/tfoot))", "", source)
    source = re.sub(r'="([A-Za-z0-9_:/.,?&;%#+~-]+)"', r"=\1", source)
    source = re.sub(r"(<(?:img|meta|br)\b[^>]*?)/>", r"\1>", source)
    source = re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                    lambda match: match[1] + match[2].replace("}", "}\n") + match[3],
                    source, flags=re.DOTALL)
    source = re.sub(r"<(tr|table|thead|tbody|div|p|h1|h2|style|br)(?=[\s>])", r"<\1\n", source)
    if max((len(line.encode("utf-8")) for line in source.splitlines()), default=0) > 998:
        raise RuntimeError("Native body exceeds the SMTP line limit; never remove candidates")
    return source

def _compact(source):
    doc = BeautifulSoup(source, "html5lib")
    for table in doc.select("table.stock-table, table.new-table"):
        table["class"] = list(table.get("class", [])) + ["c"]
        for cell in table.select("tbody td"):
            remaining = [item for item in cell.get("class", []) if item not in ("n", "r", "f")]
            if remaining:
                cell["class"] = remaining
            else:
                cell.attrs.pop("class", None)
    for table in doc.select(".etf-comparison table"):
        table["class"] = list(table.get("class", [])) + ["v"]
    for cell in doc.select(".etf-comparison tbody td"):
        remaining = [item for item in cell.get("class", [])
                     if item not in ("n", "f", "y", "p1", "p3", "p5", "p10", "d")]
        if remaining:
            cell["class"] = remaining
        else:
            cell.attrs.pop("class", None)
        for metric in cell.select("b"):
            remaining = [item for item in metric.get("class", []) if item != "m"]
            if remaining:
                metric["class"] = remaining
            else:
                metric.attrs.pop("class", None)
    for style in doc.find_all("style"):
        style.string = _trim_css(str(style.string or ""), doc)
    style = doc.new_tag("style")
    style.string = _column_css()
    doc.head.append(style)
    return _transport(str(doc))

def _facts(source, expected):
    doc = BeautifulSoup(source, "html5lib")
    actual = email_layout.validate_inventory(source, expected)
    _numbers(doc)
    return doc, actual, semantic_digest(doc)

def prepare(source, expected, directory):
    original, actual, semantics = _facts(source, expected)
    delivery = _compact(source)
    doc, checked, after_semantics = _facts(delivery, expected)
    if after_semantics != semantics:
        raise RuntimeError("Native compaction changed a field, link, flag or table structure")
    print("NATIVE_BODY_MEASURE:" + json.dumps({
        "raw":len(delivery.encode("utf-8")),
        "canonical":len(str(doc).encode("utf-8")),
        "class_attributes":len(doc.select("[class]")),
        "style_characters":sum(len(str(tag.string or "")) for tag in doc.find_all("style")),
    }), flush=True)
    size, canonical = validate_delivery_size(delivery)
    meta = {"source_sha256": digest(source.encode("utf-8")),
            "delivery_sha256": digest(delivery.encode("utf-8")),
            "semantic_sha256": semantics, "inventory": actual,
            "native_tables": [table.get("id") for table in doc.select("table.data-table")],
            "html_bytes": size, "canonical_bytes": canonical,
            "style_characters": sum(len(str(tag.string or "")) for tag in doc.find_all("style")),
            "links_sha256": digest(json.dumps(
                [(a.get("href"), a.get_text()) for a in original.body.find_all("a")],
                ensure_ascii=False).encode("utf-8"))}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "email-delivery.html").write_text(delivery, encoding="utf-8")
    (directory / "native-report.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return delivery, meta

def verify_package(source, delivery, expected, meta, directory):
    original, actual, semantics = _facts(source, expected)
    doc, checked, after_semantics = _facts(delivery, expected)
    size, canonical = validate_delivery_size(delivery)
    links_sha = digest(json.dumps([(a.get("href"), a.get_text()) for a in original.body.find_all("a")],
                                 ensure_ascii=False).encode("utf-8"))
    wanted = {"source_sha256": digest(source.encode("utf-8")),
              "delivery_sha256": digest(delivery.encode("utf-8")),
              "semantic_sha256": semantics, "inventory": actual,
              "native_tables": [table.get("id") for table in doc.select("table.data-table")],
              "html_bytes": size, "canonical_bytes": canonical,
              "style_characters": sum(len(str(tag.string or "")) for tag in doc.find_all("style")),
              "links_sha256": links_sha}
    if meta != wanted or semantics != after_semantics or delivery != _compact(source):
        raise RuntimeError("Native delivery differs from the complete verified source")
    directory = Path(directory)
    if ((directory / "email-delivery.html").read_text(encoding="utf-8") != delivery or
            json.loads((directory / "native-report.json").read_text(encoding="utf-8")) != meta):
        raise RuntimeError("Native delivery files changed after preparation")
    return {}

def plain_report(source):
    doc = BeautifulSoup(source, "html5lib")
    return doc.body.get_text(" ", strip=True) if doc.body else doc.get_text(" ", strip=True)
