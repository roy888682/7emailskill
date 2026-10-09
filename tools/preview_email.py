#!/usr/bin/env python3
"""Verify all email rows in both standalone and Gmail-style desktop hosts."""
import argparse
import base64
import hashlib
import json
import io
from PIL import Image
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_HTML_BYTES = 200000

def make_stock(ticker, market="US", number=0, asset_type="주식"):
    korean = market != "US"
    name = ("한국차세대반도체인공지능산업솔루션장기성장기업 " + ticker if korean else
            "International Artificial Intelligence Semiconductor Infrastructure Holdings " + ticker)
    return {"ticker": ticker, "name": name, "market": "KOSPI" if korean else "US",
            "asset_type": asset_type, "price": 178950 if korean else 238.71,
            "change": round((number % 13 - 6) * .43, 2),
            "gap": round(-9.9 + (number % 100) * .099, 2),
            "mcap": round(1.2 + (number % 80) * .6, 1),
            "industry": "반도체 장비·소재 및 인공지능 인프라",
            "index": ["KOSPI"] if korean else ["S&P500", "NASDAQ"],
            "streak": 1 + number % 67,
            "url": ("https://m.stock.naver.com/domestic/stock/" + ticker + "/total" if korean else
                    "https://m.stock.naver.com/worldstock/stock/" + ticker + "/total")}

def sample_data():
    us = [make_stock("US%04d" % i, number=i) for i in range(203)]
    kr = [make_stock("KR%04d" % i, market="KOSPI", number=i) for i in range(7)]
    us_etfs = [("SOXL", "Direxion Daily Semiconductor Bull 3X Shares"),
               ("SMH", "VanEck Semiconductor ETF"), ("SOXX", "iShares Semiconductor ETF"),
               ("TQQQ", "ProShares UltraPro QQQ"), ("QQQ", "Invesco QQQ Trust, Series 1"),
               ("VGT", "Vanguard Information Technology ETF"), ("SPY", "SPDR S&P 500 ETF Trust"),
               ("VOO", "Vanguard S&P 500 ETF"), ("GLD", "SPDR Gold Shares"),
               ("SCHD", "Schwab US Dividend Equity ETF")]
    kr_etfs = [("455850", "SOL AI반도체소부장"), ("381180", "TIGER 미국필라델피아반도체나스닥"),
               ("133690", "TIGER 미국나스닥100"), ("379810", "KODEX 미국나스닥100"),
               ("360750", "TIGER 미국S&P500"), ("379800", "KODEX 미국S&P500"),
               ("161510", "PLUS 고배당주"), ("069500", "KODEX 200"),
               ("102110", "TIGER 200"), ("411060", "ACE KRX금현물")]
    etfs = []
    for index in range(10):
        for korean, pair in ((True, kr_etfs[index]), (False, us_etfs[index])):
            ticker, name = pair
            rank = len(etfs)
            item = make_stock(ticker, market="KOSPI" if korean else "US", number=rank, asset_type="ETF")
            item.update({"name": name, "aum": round(2.5 + rank * 1.35, 1),
                         "cagr1y": round(82.35 - rank * 3.67, 2),
                         "cagr3y": round(39.28 - rank * 1.5, 2),
                         "cagr5y": None if rank % 7 == 0 else round(24.46 - rank * .67, 2),
                         "cagr10y": None if rank % 3 == 0 else round(18.33 - rank * .31, 2),
                         "cumulative_return": (103383.7 if rank == 1 else -103383.7 if rank == 3 else round(1280.43 - rank * 44.21, 2)),
                         "etf_index": "FnGuide 차세대 인공지능 반도체 소부장 산업 지수" if korean else
                                      "Philadelphia Semiconductor Sector Total Return Index",
                         "issuer": "신한자산운용 주식회사" if korean else "Vanguard Group, Inc.",
                         "etf_kind": "레버리지·성장주" if rank < 4 else "주식형·대표지수",
                         "inception": "2016-05-19"})
            etfs.append(item)
            (kr if korean else us).append(item)
    info = {"us_last_str": "2026년 10월 07일(수)", "kr_last_str": "2026년 10월 07일(수)",
            "us_holiday": False, "kr_holiday": False, "us_holiday_msg": "", "kr_holiday_msg": ""}
    return {"us": us, "kr": kr, "info": info, "usd_krw": 1343.4, "new_us": us[:119], "new_kr": kr[:1],
            "diag": {"us_days_before": 66, "kr_days_before": 59},
            "indices": {"sp500": 7801.77, "kospi": 6625.93, "sp500_chg": -.22, "kospi_chg": -2.62},
            "etf_info": {"rows": etfs, "pool": 126, "with_ret": 124}}


def preview_data():
    data = sample_data()
    data["new_us"] = data["new_us"][:10]
    return data

def build_preview_html():
    from src.email_layout import render_email
    return render_email(**preview_data())

def manifest_for(data):
    return {
        "us": [str(row["ticker"]) for row in data["us"]],
        "kr": [str(row["ticker"]) for row in data["kr"]],
        "new": [
            country + ":" + str(row["ticker"])
            for country, rows in (("KR", data["new_kr"]), ("US", data["new_us"]))
            for row in rows
        ],
        "etf": [str(row["ticker"]) for row in data["etf_info"]["rows"]],
    }

def normalize_manifest(raw):
    result = {}
    for key in ("us", "kr", "new", "etf"):
        items = raw.get(key)
        if items is None:
            raise ValueError("Manifest is missing %r" % key)
        if key == "new" and isinstance(items, dict):
            items = [
                country + ":" + str(item["ticker"] if isinstance(item, dict) else item)
                for country, values in (("KR", items.get("kr", [])), ("US", items.get("us", [])))
                for item in values
            ]
        if not isinstance(items, list):
            raise ValueError("Manifest %r must be a list" % key)
        result[key] = [
            str(item["ticker"]) if isinstance(item, dict) else str(item)
            for item in items
        ]
    return result

def gmail_host_html(html_source):
    """Keep message CSS but remove its body rule to model Gmail's 16px host."""
    html_source = re.sub(
        r"(?<![\w.#-])body\s*\{[^}]*\}", "", html_source,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"<body\b[^>]*>",
        '<body style="margin:0;font:16px Arial,sans-serif;line-height:normal;'
        'background:white;color:black">',
        html_source, count=1, flags=re.IGNORECASE,
    )

LAYOUT_CHECK = r"""expected => {
 const viewport=window.innerWidth,tolerance=1.5,problems=[];
 const specs=[
   ["us","us",2,11],["kr","kr",2,11],
   ["new","new",2,10],["etf","returns",2,11]
 ];
 const getRows=id=>{
   const table=document.getElementById(id);
   return table?Array.from(table.tBodies).flatMap(body=>Array.from(body.rows)):[];
 };
 const all=[],counts={};
 if(document.documentElement.scrollWidth>viewport+tolerance)
   problems.push("Document overflow: "+document.documentElement.scrollWidth+" > "+viewport);
 for(const [key,id,tickerColumn,cellCount] of specs){
   const rows=getRows(id),wanted=expected[key];
   const table=document.getElementById(id);
   if(table&&table.querySelector("th")?.textContent.trim()!=="No.")
     problems.push(id+" is missing the No. heading");
   const tickers=rows.map(row=>{
     const cell=row.cells[tickerColumn],link=cell&&cell.querySelector("a");
     if(!link){problems.push(id+" is missing a ticker link");return "";}
     const ticker=Array.from(link.childNodes)
       .filter(node=>node.nodeType===Node.TEXT_NODE)
       .map(node=>node.textContent).join("").trim();
     if(key==="new"){
       const label=row.cells[1]?.querySelector("img")?.alt||"";
       if(!["성조기","태극기"].includes(label))
         problems.push("New-security flag lacks a recognizable country label");
       return (label==="성조기"?"US":"KR")+":"+ticker;
     }
     return ticker;
   });
   counts[key]={expected:wanted.length,visible:rows.length};
   if(JSON.stringify(tickers)!==JSON.stringify(wanted)){
     const missing=wanted.filter(ticker=>!tickers.includes(ticker));
     const extra=tickers.filter(ticker=>!wanted.includes(ticker));
     problems.push(id+" ticker/order mismatch; missing="+missing.join(",")+" extra="+extra.join(","));
   }
   if(new Set(tickers).size!==tickers.length)
     problems.push(id+" contains duplicate securities");
   rows.forEach((row,index)=>{
     if(row.cells.length!==cellCount)
       problems.push(id+" row "+index+" has "+row.cells.length+" cells, expected "+cellCount);
     if(row.cells[0]?.textContent.trim()!==String(index+1))
       problems.push(id+" row "+index+" has a missing or incorrect No.");
     const flag=row.cells[1]?.querySelector("img");
     if(!flag||!flag.complete||!flag.naturalWidth)
       problems.push(id+" row "+index+" has a missing/broken country flag");
   });
   all.push(...rows);
 }
 const returns=document.getElementById("returns"),newTable=document.getElementById("new");
 if(newTable&&returns&&!(newTable.compareDocumentPosition(returns)&Node.DOCUMENT_POSITION_FOLLOWING))
   problems.push("The new-security list must precede ETF returns");
 const allHeaders=Array.from(document.querySelectorAll("th")).map(cell=>cell.textContent).join(" ");
 if(allHeaders.includes("현재가"))problems.push("Current-price column remains");
 if(document.body.textContent.includes("첨부"))problems.push("Attachment-related copy remains");
 if(returns){
   const headings=Array.from(returns.querySelectorAll("thead th")).map(cell=>cell.textContent.trim());
   if(headings.length!==11||!headings[8].includes("누적")||
      !/AUM|시총/.test(headings[9])||!headings[10].includes("설립"))
     problems.push("ETF columns must end with cumulative → KRW AUM → inception");
 }
 getRows("returns").forEach((row,index)=>{
   const colors=[];
   for(const [column,cls] of [[4,"p1"],[5,"p3"],[6,"p5"],[7,"p10"]]){
     const cell=row.cells[column];
     if(!cell||!cell.classList.contains(cls))
       problems.push("ETF "+index+" is missing "+cls+" on the correct return column");
     if(cell)colors.push(getComputedStyle(cell).color);
   }
   if(new Set(colors).size!==4)problems.push("ETF "+index+" return colors are not distinct");
 });
 [...getRows("us"),...getRows("kr"),...getRows("new")].forEach(row=>{
   for(const column of [6,8]){
     const cell=row.cells[column];
     if(!cell||getComputedStyle(cell).color!=="rgb(194, 57, 50)")
       problems.push("ATH/day-change values must be red");
   }
 });
 const stockBadge=document.querySelector(".stock-table b,.new-table b"),etfBadge=document.querySelector(".stock-table i,.new-table i");
 if(stockBadge&&etfBadge){
   const signature=el=>{
     const style=getComputedStyle(el);
     return style.color+"|"+style.backgroundColor;
   };
   if(signature(stockBadge)===signature(etfBadge))
     problems.push("Stock and ETF badges have identical colors");
 }
 all.forEach((row,index)=>{
   const box=row.getBoundingClientRect();
   if(box.height>32)problems.push("Row "+index+" is taller than one line: "+box.height);
   if(box.left< -tolerance||box.right>viewport+tolerance)
     problems.push("Row "+index+" exceeds the viewport");
   for(const cell of row.cells){
     const style=getComputedStyle(cell),bounds=cell.getBoundingClientRect();
     if(style.whiteSpace!=="nowrap")problems.push("Row "+index+" permits wrapping");
     if(parseFloat(style.fontSize)>12)problems.push("Row "+index+" inherits a large host font");
     const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);let node;
     while((node=walker.nextNode())){
       if(!node.textContent.trim())continue;
       const range=document.createRange();range.selectNodeContents(node);
       const rects=Array.from(range.getClientRects()).filter(rect=>rect.width);
       if(rects.length>1)problems.push("Row "+index+" wraps: "+node.textContent.trim());
       for(const rect of rects)
         if(rect.left<bounds.left-tolerance||rect.right>bounds.right+tolerance)
           problems.push("Row "+index+" clips text: "+node.textContent.trim());
     }
   }
 });
 const broken=Array.from(document.images).filter(image=>!image.complete||!image.naturalWidth);
 if(broken.length)problems.push("Broken images: "+broken.map(image=>image.alt).join(","));
 return {
   viewport,counts,
   etfHeight:Math.round(returns?.getBoundingClientRect().height||0),
   shellFont:document.querySelector(".shell")?getComputedStyle(document.querySelector(".shell")).fontSize:null,
   problems
 };
}"""

def cropped_table_image(page, table_id, output, marker):
    if not page.locator("#" + table_id).count():
        return
    page.evaluate("(id)=>document.getElementById(id).scrollIntoView({block:'start'})", table_id)
    box = page.locator("#" + table_id).bounding_box()
    if not box:
        return
    viewport = page.viewport_size
    clip = {
        "x": max(0, box["x"]),
        "y": max(0, box["y"]),
        "width": min(box["width"], viewport["width"] - max(0, box["x"])),
        "height": min(box["height"], 480, viewport["height"] - max(0, box["y"])),
    }
    if clip["width"] <= 0 or clip["height"] <= 0:
        raise AssertionError("Screenshot target lies outside the viewport")
    png = page.screenshot(path=str(output), clip=clip)
    print(marker + ":" + base64.b64encode(png).decode("ascii"), flush=True)


NATIVE_SNAPSHOT = r"""() => {
 const properties=["fontFamily","fontSize","fontWeight","fontStyle","lineHeight",
  "letterSpacing","fontVariantNumeric","textAlign","whiteSpace","paddingTop",
  "paddingRight","paddingBottom","paddingLeft","color","backgroundColor",
  "borderTopWidth","borderBottomWidth","verticalAlign"];
 const result={};
 for(const id of ["us","kr","new","returns"]){
  const table=document.getElementById(id);
  result[id]=table?Array.from(table.rows).map(row=>Array.from(row.cells).map(cell=>{
   const style=getComputedStyle(cell);
   return {tag:cell.tagName,text:cell.textContent.trim(),
    links:Array.from(cell.querySelectorAll("a")).map(a=>[a.textContent.trim(),a.getAttribute("href")]),
    flags:Array.from(cell.querySelectorAll("img")).map(img=>[img.getAttribute("src"),img.alt]),
    style:Object.fromEntries(properties.map(key=>[key,style[key]]))};
  })):[];
 }
 return result;
}"""

NATIVE_CONTENT = r"""() => {
 const result={};
 for(const id of ["us","kr","new","returns"]){
  const table=document.getElementById(id);
  result[id]=table?Array.from(table.rows).map(row=>Array.from(row.cells).map(cell=>({
   tag:cell.tagName,text:cell.textContent.trim(),
   links:Array.from(cell.querySelectorAll("a")).map(a=>[a.textContent.trim(),a.getAttribute("href")]),
   flags:Array.from(cell.querySelectorAll("img")).map(img=>[img.getAttribute("src"),img.alt])
  }))):[];
 }
 return result;
}"""

NATIVE_FONT_CHECK = r"""() => {
 const us=document.querySelector("#us tbody tr"),kr=document.querySelector("#kr tbody tr");
 if(!us||!kr)return {compared:false,all_match:true,measurements:[]};
 const properties=["fontFamily","fontSize","fontWeight","fontStyle","lineHeight","letterSpacing"];
 const measure=element=>{
  const style=getComputedStyle(element),span=document.createElement("span");
  for(const key of [...properties,"fontVariantNumeric"])span.style[key]=style[key];
  Object.assign(span.style,{position:"absolute",visibility:"hidden",whiteSpace:"nowrap",padding:"0",border:"0",margin:"0"});
  span.textContent="Ag0123456789한국";
  element.appendChild(span);
  const bounds=span.getBoundingClientRect();
  const result={style:Object.fromEntries(properties.map(key=>[key,style[key]])),
                width:bounds.width,height:bounds.height};
  span.remove();
  return result;
 };
 const pairs=Array.from(us.cells).map((cell,index)=>[cell,kr.cells[index],index]);
 pairs.push([us.cells[2].querySelector("a"),kr.cells[2].querySelector("a"),"ticker"]);
 const measurements=pairs.map(([first,second,column])=>{
  const american=measure(first),korean=measure(second);
  const match=JSON.stringify(american.style)===JSON.stringify(korean.style)&&
    Math.abs(american.width-korean.width)<.01&&Math.abs(american.height-korean.height)<.01;
  return {column,us:american,kr:korean,match};
 });
 return {compared:true,all_match:measurements.every(value=>value.match),measurements};
}"""


def verify_actual_display(browser, source, delivery, expected, output):
    """Compare native text, links and pixels with the complete accepted source."""
    from src.email_flags import inline_flag_sources
    document = inline_flag_sources(delivery)
    if re.search(r"cid:us-report-|id=['\"]us-display", delivery):
        raise AssertionError("US delivery must use native HTML text")
    for host in ("standalone", "gmail"):
        for width in (900, 1024, 1280, 1600, 1920):
            original = browser.new_page(viewport={"width":width,"height":1200},device_scale_factor=1)
            displayed = browser.new_page(viewport={"width":width,"height":1200},device_scale_factor=1)
            try:
                original.set_content(gmail_host_html(source) if host=="gmail" else source,wait_until="load")
                displayed.set_content(gmail_host_html(document) if host=="gmail" else document,wait_until="load")
                for page in (original,displayed):
                    page.evaluate("document.fonts.ready")
                    if page.evaluate("document.documentElement.scrollWidth>window.innerWidth+1.5"):
                        raise AssertionError("Actual native delivery overflows the desktop window")
                    if page.evaluate("Array.from(document.images).some(img=>!img.complete||!img.naturalWidth)"):
                        raise AssertionError("Actual native delivery contains a broken country flag")
                content = original.evaluate(NATIVE_CONTENT)
                if displayed.evaluate(NATIVE_CONTENT)!=content:
                    raise AssertionError("Native delivery changed a row, number, field, flag or ticker link")
                actual_styles=displayed.evaluate(NATIVE_SNAPSHOT)
                original_styles=original.evaluate(NATIVE_SNAPSHOT)
                if actual_styles!=original_styles:
                    mismatches=[]
                    for table_id,rows in original_styles.items():
                        for row_index,row in enumerate(rows):
                            for cell_index,cell in enumerate(row):
                                actual=actual_styles[table_id][row_index][cell_index]
                                if actual!=cell:
                                    mismatches.append({"table":table_id,"row":row_index,"column":cell_index,
                                        "expected":cell,"actual":actual})
                    print("NATIVE_STYLE_MISMATCH:"+json.dumps(mismatches[:3],ensure_ascii=False),flush=True)
                    raise AssertionError("Native delivery changed a table font, color, padding or alignment")
                before = Image.open(io.BytesIO(original.screenshot(full_page=True))).convert("RGB")
                after = Image.open(io.BytesIO(displayed.screenshot(full_page=True))).convert("RGB")
                if before.size!=after.size or before.tobytes()!=after.tobytes():
                    raise AssertionError("Native delivery differs from the accepted layout at %dpx (%s)" % (width,host))
                font_check = displayed.evaluate(NATIVE_FONT_CHECK)
                if not font_check["all_match"]:
                    raise AssertionError("Native US and Korean fonts or identical sample glyphs differ")
                links = displayed.locator("#us tbody tr td:nth-child(3) a")
                source_urls = original.locator("#us tbody tr td:nth-child(3) a").evaluate_all(
                    "(links)=>links.map(link=>link.getAttribute('href'))")
                if links.count()!=len(expected["us"]) or len(source_urls)!=len(expected["us"]):
                    raise AssertionError("Every native US row must have its own Naver ticker link")
                if any(not re.fullmatch(r"https://m\.stock\.naver\.com/worldstock/(?:stock|etf)/[A-Za-z0-9._-]+(?:/total)?",url)
                       for url in source_urls):
                    raise AssertionError("A US ticker link does not target Naver")
                displayed.evaluate("""()=>{
                    window.verifiedClicks=[];
                    document.addEventListener("click",event=>{
                        const link=event.target.closest("#us tbody td a");
                        if(link){event.preventDefault();window.verifiedClicks.push(link.getAttribute("href"));}
                    },true);
                }""")
                for index,url in enumerate(source_urls):
                    link=links.nth(index)
                    if link.get_attribute("href")!=url:
                        raise AssertionError("Native US ticker links changed order")
                    link.scroll_into_view_if_needed()
                    bounds=link.bounding_box()
                    displayed.mouse.click(bounds["x"]+bounds["width"]/2,bounds["y"]+bounds["height"]/2)
                if displayed.evaluate("window.verifiedClicks")!=source_urls:
                    raise AssertionError("A native US ticker does not open its own Naver URL")
                print("US_LINK_CLICK_QA:"+json.dumps({"host":host,"viewport":width,
                      "clicked":len(source_urls),"all_match":True,"native":True}),flush=True)
                print("US_FONT_MATCH_QA:"+json.dumps({"host":host,"viewport":width,
                      "all_match":True,"native":True,"metrics":font_check}),flush=True)
                print("DELIVERY_DISPLAY_QA:"+json.dumps({"host":host,"viewport":width,
                      "us":len(expected["us"]),"native":True,"pixels_identical":True,
                      "all_rows_fields_links_preserved":True}),flush=True)
                if host=="gmail" and width==1600:
                    for table_id,filename,marker in (
                        ("us","email-actual-native-us.png","PREVIEW_IMAGE_ACTUAL_DELIVERY_US"),
                        ("kr","email-actual-native-kr.png","PREVIEW_IMAGE_ACTUAL_DELIVERY_KR"),
                    ):
                        cropped_table_image(displayed,table_id,output/filename,marker)
                    if displayed.locator("#us tbody tr").count() and displayed.locator("#kr tbody tr").count():
                        kr_rows=displayed.locator("#kr tbody tr")
                        kr=kr_rows.nth(max(0,kr_rows.count()-3)).bounding_box()
                        us_rows=displayed.locator("#us tbody tr")
                        us=us_rows.nth(min(4,us_rows.count()-1)).bounding_box()
                        section=displayed.locator("#us").bounding_box()
                        clip={"x":section["x"],"y":kr["y"],"width":section["width"],
                              "height":us["y"]+us["height"]-kr["y"]}
                        png=displayed.screenshot(path=str(output/"email-native-font-comparison.png"),clip=clip)
                        print("PREVIEW_IMAGE_NATIVE_KR_US_FONTS:"+base64.b64encode(png).decode("ascii"),flush=True)
                # Model Gmail/browser minimum-font expansion on both native tables.
                displayed.add_style_tag(content=""".data-table td,.data-table th,
                    .data-table td a,.data-table td b,.data-table td i{font-size:18px!important}""")
                expanded = displayed.evaluate(NATIVE_FONT_CHECK)
                if not expanded["all_match"] or displayed.evaluate(NATIVE_CONTENT)!=content:
                    raise AssertionError("Native US/Korean font expansion differs or changes report content")
                if expanded["compared"] and any(
                    abs(float(pair[country]["style"]["fontSize"].removesuffix("px"))-18)>.001
                    for pair in expanded["measurements"] for country in ("us","kr")
                ):
                    raise AssertionError("Minimum-font simulation did not expand both native tables")
                print("NATIVE_HIGH_FONT_QA:"+json.dumps({"host":host,"viewport":width,
                      "font_px":18,"all_match":True,"all_rows_preserved":True}),flush=True)
            finally:
                original.close()
                displayed.close()
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "work")
    args = parser.parse_args()
    if args.html and not args.manifest:
        parser.error("--manifest is required with --html to verify every candidate")
    from src.email_flags import inline_flag_sources
    from src.main import compose_email_message
    from src import report_inline, native_email
    from playwright.sync_api import sync_playwright
    args.output.mkdir(parents=True, exist_ok=True)
    proof_path = args.output / "preview-passed.json"
    proof_path.unlink(missing_ok=True)
    if args.html:
        source = args.html.read_text(encoding="utf-8")
        expected = normalize_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    else:
        source = build_preview_html()
        data = preview_data()
        expected = manifest_for(data)
    size = len(source.encode("utf-8"))
    print("PREVIEW_HTML_BYTES:%d" % size, flush=True)
    if args.html and size > MAX_HTML_BYTES:
        raise AssertionError("HTML body %d bytes exceeds %d-byte budget" % (size, MAX_HTML_BYTES))
    html_source = inline_flag_sources(source)
    gmail_source = gmail_host_html(html_source)
    if args.reference:
        reference = inline_flag_sources(args.reference.read_text(encoding="utf-8"))
    elif not args.html:
        from src.email_layout import render_email
        reference = inline_flag_sources(render_email(**preview_data(), compact=False))
    else:
        parser.error("--reference is required to verify the unchanged layout")
    reference_gmail = gmail_host_html(reference)
    (args.output / "email-preview.html").write_text(html_source, encoding="utf-8")
    (args.output / "email-preview-gmail.html").write_text(gmail_source, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for host, document in (("standalone", html_source), ("gmail", gmail_source)):
                for width in (900, 1024, 1280, 1600, 1920):
                    page = browser.new_page(
                        viewport={"width": width, "height": 1200}, device_scale_factor=1,
                    )
                    try:
                        page.set_content(document, wait_until="load")
                        page.evaluate("document.fonts.ready")
                        result = page.evaluate(LAYOUT_CHECK, expected)
                        result["host"] = host
                        print("LAYOUT_QA:%s" % json.dumps(result, ensure_ascii=False), flush=True)
                        if result["problems"]:
                            raise AssertionError("; ".join(result["problems"]))
                        reference_page = browser.new_page(viewport={"width":width,"height":1200},device_scale_factor=1)
                        try:
                            reference_page.set_content(reference_gmail if host=="gmail" else reference,wait_until="load")
                            reference_page.evaluate("document.fonts.ready")
                            actual_pixels = Image.open(io.BytesIO(page.screenshot(full_page=True))).convert("RGB")
                            original_pixels = Image.open(io.BytesIO(reference_page.screenshot(full_page=True))).convert("RGB")
                            if actual_pixels.size != original_pixels.size or actual_pixels.tobytes() != original_pixels.tobytes():
                                raise AssertionError("Rendered layout differs from the accepted style at %dpx (%s)" % (width,host))
                            print("LAYOUT_IDENTICAL:%s:%d" % (host,width),flush=True)
                        finally:
                            reference_page.close()
                        if host == "gmail" and width == 1600:
                            for table_id, filename, marker in (
                                ("returns", "email-desktop-etf.png", "PREVIEW_IMAGE_DESKTOP_ETF"),
                                ("new", "email-desktop-new.png", "PREVIEW_IMAGE_DESKTOP_NEW"),
                                ("us", "email-desktop-stocks.png", "PREVIEW_IMAGE_DESKTOP_STOCKS"),
                            ):
                                cropped_table_image(page, table_id, args.output / filename, marker)
                    finally:
                        page.close()
            delivery,package=native_email.prepare(source,expected,args.output)
            assets=native_email.verify_package(source,delivery,expected,package,args.output)
            if assets != {}:
                raise AssertionError("Native production delivery must not contain report PNGs")
            wire=compose_email_message(delivery,"ATH 기본표","sender@example.test","reader@example.test",
                                       {})
            print("DELIVERY_HTML_BYTES:%d" % len(delivery.encode("utf-8")),flush=True)
            print("DELIVERY_CANONICAL_BYTES:%d" % native_email.validate_delivery_size(delivery)[1],flush=True)
            print("DELIVERY_WIRE_BYTES:%d" % len(wire.as_bytes()),flush=True)
            print("US_NATIVE_COVERAGE:%d" % len(expected["us"]),flush=True)
            us_font_matches_kr=verify_actual_display(browser,html_source,delivery,expected,args.output)
        finally:
            browser.close()
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    proof = {
        "sha256": digest, "body_sha256": digest, "html_bytes": size,
        "counts": {key: len(values) for key, values in expected.items()},
        "viewports": [900, 1024, 1280, 1600, 1920],
        "hosts": ["standalone", "gmail"], "all_passed": True, "layout_unchanged": True,
        "delivery_sha256":hashlib.sha256(delivery.encode("utf-8")).hexdigest(),
        "native_package_sha256":hashlib.sha256((args.output/"native-report.json").read_bytes()).hexdigest(),
        "delivery_checked":True,"delivery_viewports":[900,1024,1280,1600,1920],
        "native_checked":True,"us_font_matches_kr":us_font_matches_kr,
        "high_font_matches_kr":True,
        "us_link_clicks":len(expected["us"]),"numbering_checked":True,
    }
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PREVIEW_PASSED:%s" % json.dumps(proof, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
