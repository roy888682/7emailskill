"""Keep the large US table visually intact in a small inline email body."""
import base64
import hashlib
import io
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image
if __package__:
    from . import email_layout, email_flags
else:
    import email_layout, email_flags

MAX_HTML_BYTES=30000
MAX_CANONICAL_BYTES=40000

def digest(value):
    return hashlib.sha256(value).hexdigest()

def validate_delivery_size(html):
    size=len(html.encode("utf-8"))
    canonical=len(str(BeautifulSoup(html,"html5lib")).encode("utf-8"))
    if size>MAX_HTML_BYTES or canonical>MAX_CANONICAL_BYTES:
        raise RuntimeError(f"Display body {size:,}/{canonical:,} bytes exceeds the clipping budget; never remove candidates")
    return size,canonical

def safe_lines(html):
    html=re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                lambda m:m[1]+m[2].replace("}","}\n")+m[3],html,flags=re.DOTALL)
    html=re.sub(r"<([A-Za-z][A-Za-z0-9]*)(?=[\s/>])",r"<\1\n",html)
    return html

def make_package(source, expected, png, rows, geometry, directory):
    directory=Path(directory)
    doc=BeautifulSoup(source,"html5lib")
    if not expected["us"]:
        validate_delivery_size(source)
        meta={"source_sha256":digest(source.encode("utf-8")),"delivery_sha256":digest(source.encode("utf-8")),
              "us_tickers":[],"rows":[],"geometry":{},"width":0,"height":0,"assets":[]}
        (directory/"email-delivery.html").write_text(source,encoding="utf-8")
        (directory/"inline-report.json").write_text(json.dumps(meta,ensure_ascii=False),encoding="utf-8")
        return source,meta
    table=doc.find("table",id="us")
    if table is None:
        raise RuntimeError("US source table is missing")
    section=table.find_parent("div",class_="stock-section")
    full=Image.open(io.BytesIO(png)).convert("RGB")
    width,height=full.size
    if [r["ticker"] for r in rows]!=expected["us"]:
        raise RuntimeError("Raster row inventory does not match all US candidates")
    edges=sorted(set([0,height]+[max(0,min(height,round(r["bottom"]))) for r in rows]))
    assets=[]
    top=0
    (directory/"report-inline").mkdir(exist_ok=True)
    while top<height:
        candidates=[edge for edge in edges if top<edge<=top+900]
        bottom=max(candidates) if candidates else min(edge for edge in edges if edge>top)
        cid=f"us-report-{len(assets):02d}"
        relative=f"report-inline/{cid}.png"
        stream=io.BytesIO()
        full.crop((0,top,width,bottom)).save(stream,format="PNG",optimize=True)
        payload=stream.getvalue()
        (directory/relative).write_bytes(payload)
        assets.append({"cid":cid,"path":relative,"sha256":digest(payload),
                       "width":width,"height":bottom-top,"top":top,"bottom":bottom})
        top=bottom
    replacement=doc.new_tag("div")
    replacement["class"]=["section","stock-section"]
    replacement["id"]="us-display"
    replacement["aria-label"]=f"미국 ATH 후보 {len(expected['us'])}종목 전체"
    for index,asset in enumerate(assets,1):
        image=doc.new_tag("img",src="cid:"+asset["cid"])
        image["width"]=str(width)
        image["height"]=str(asset["height"])
        image["alt"]=f"미국 ATH 후보 전체 표 {index}/{len(assets)}"
        image["style"]=f"display:block;width:100%;max-width:{width}px;height:auto;border:0;margin:0;padding:0"
        replacement.append(image)
    section.replace_with(replacement)
    delivery=safe_lines(str(doc))
    validate_delivery_size(delivery)
    meta={"source_sha256":digest(source.encode("utf-8")),"delivery_sha256":digest(delivery.encode("utf-8")),
          "us_tickers":expected["us"],"rows":rows,"geometry":geometry,
          "width":width,"height":height,"pixels_sha256":digest(full.tobytes()),"assets":assets}
    (directory/"email-delivery.html").write_text(delivery,encoding="utf-8")
    (directory/"inline-report.json").write_text(json.dumps(meta,ensure_ascii=False),encoding="utf-8")
    return delivery,meta

def verify_package(source,delivery,expected,meta,directory):
    directory=Path(directory).resolve()
    if meta.get("source_sha256")!=digest(source.encode("utf-8")) or meta.get("delivery_sha256")!=digest(delivery.encode("utf-8")):
        raise RuntimeError("Inline report does not match the verified source")
    if meta.get("us_tickers")!=expected["us"] or [r["ticker"] for r in meta.get("rows",[])]!=expected["us"]:
        raise RuntimeError("Inline report is missing US candidates")
    actual=email_layout.inventory(delivery)
    if actual!={**expected,"us":[]}:
        raise RuntimeError("Non-US tables changed during inline packaging")
    validate_delivery_size(delivery)
    doc=BeautifulSoup(delivery,"html5lib")
    images=doc.select("#us-display img")
    assets=meta.get("assets",[])
    if not expected["us"] and not assets and not images:
        return {}
    if not assets or [img.get("src") for img in images]!=["cid:"+a["cid"] for a in assets]:
        raise RuntimeError("Inline report images are missing or out of order")
    canvas=Image.new("RGB",(meta["width"],meta["height"]))
    payloads={}
    cursor=0
    for asset in assets:
        path=(directory/asset["path"]).resolve()
        if not path.is_relative_to(directory) or not re.fullmatch(r"us-report-\d{2}",asset["cid"]):
            raise RuntimeError("Invalid inline report asset path")
        payload=path.read_bytes()
        picture=Image.open(io.BytesIO(payload)).convert("RGB")
        if digest(payload)!=asset["sha256"] or picture.size!=(meta["width"],asset["height"]):
            raise RuntimeError("Inline report image changed after browser validation")
        if asset["top"]!=cursor or asset["bottom"]!=cursor+asset["height"]:
            raise RuntimeError("Inline report has a missing or overlapping image segment")
        canvas.paste(picture,(0,cursor))
        cursor=asset["bottom"]
        payloads[asset["cid"]]=payload
    if cursor!=meta["height"] or digest(canvas.tobytes())!=meta["pixels_sha256"]:
        raise RuntimeError("Inline report pixels are incomplete")
    for row in meta["rows"]:
        center=(row["top"]+row["bottom"])/2
        if not 0<=row["top"]<row["bottom"]<=meta["height"] or sum(a["top"]<=center<a["bottom"] for a in assets)!=1:
            raise RuntimeError("A US security is missing from the inline report")
    return payloads

def inline_sources(html,payloads):
    html=email_flags.inline_flag_sources(html)
    for cid,payload in payloads.items():
        html=html.replace("cid:"+cid,"data:image/png;base64,"+base64.b64encode(payload).decode("ascii"))
    return html

def plain_report(source):
    doc=BeautifulSoup(source,"html5lib")
    return doc.body.get_text(" ",strip=True)
