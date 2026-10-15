#!/usr/bin/env python3
"""Verify all email rows in both standalone and Gmail-style desktop hosts."""
import argparse
import base64
import hashlib
import json
import io
from datetime import date
from PIL import Image
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    lifetime_years = (date(2026, 10, 7) - date(2016, 5, 19)).days / 365.25
    for index in range(10):
        for korean, pair in ((True, kr_etfs[index]), (False, us_etfs[index])):
            ticker, name = pair
            rank = len(etfs)
            cumulative = (-99.7 if rank == 0 else -42.3 if rank == 1 else
                          103383.7 if rank == 19 else round((rank - 2) * 80.43, 2))
            initial_price = .123456789 if rank == 0 else 100.123456789 + rank
            item = make_stock(ticker, market="KOSPI" if korean else "US", number=rank, asset_type="ETF")
            item.update({"name": name, "aum": round(2.5 + rank * 1.35, 1),
                         "cagr1y": round(82.35 - rank * 3.67, 2),
                         "cagr3y": round(39.28 - rank * 1.5, 2),
                         "cagr5y": None if rank % 7 == 0 else round(24.46 - rank * .67, 2),
                         "cagr10y": None if rank % 3 == 0 else round(18.33 - rank * .31, 2),
                         "cumulative_return": cumulative,
                         "initial_adjusted_price": initial_price,
                         "latest_adjusted_price": initial_price * (1 + cumulative / 100),
                         "price_start_date": "2016-05-19", "price_end_date": "2026-10-07",
                         "price_currency": "KRW" if korean else "USD",
                         "price_basis": "네이버 차트 종가·배당조정 미확인" if korean else "Yahoo 제공 수정주가(auto_adjust)",
                         "lifetime_cagr": ((1 + cumulative / 100) ** (1 / lifetime_years) - 1) * 100,
                         "lifetime_years": lifetime_years,
                         "etf_index": "FnGuide 차세대 인공지능 반도체 소부장 산업 지수" if korean else
                                      "Philadelphia Semiconductor Sector Total Return Index",
                         "issuer": "신한자산운용 주식회사" if korean else "Vanguard Group, Inc.",
                         "etf_kind": "레버리지·성장주" if rank < 4 else "주식형·대표지수",
                         "investment_area": "한국반도체" if korean else "미국반도체",
                         "inception": "2016-05-19", "first_date": "2016-05-19",
                         "last_date": "2026-10-07", "return_as_of": "2026-10-07"})
            etfs.append(item)
            (kr if korean else us).append(item)
    etfs.sort(key=lambda item: item["lifetime_cagr"], reverse=True)
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
   ["new","new-kr",2,10,"KR"],["new","new-us",2,10,"US"],
   ["etf","returns",2,16]
 ];
 const getRows=id=>{
   const table=document.getElementById(id);
   return table?Array.from(table.tBodies).flatMap(body=>Array.from(body.rows)):[];
 };
 const all=[],counts={};
 if(document.documentElement.scrollWidth>viewport+tolerance)
   problems.push("Document overflow: "+document.documentElement.scrollWidth+" > "+viewport);
 for(const [key,id,tickerColumn,cellCount,country] of specs){
   const rows=getRows(id),wanted=key==="new"?expected.new.filter(ticker=>ticker.startsWith(country+":")):expected[key];
   const table=document.getElementById(id);
   if(table&&table.querySelector("th")?.textContent.trim()!=="No.")
     problems.push(id+" is missing the No. heading");
   if(table&&getComputedStyle(table).tableLayout!=="fixed")
     problems.push(id+" must use fixed column widths for bounded ellipses");
   for(const heading of table?.querySelectorAll("thead th")||[]){
     if(getComputedStyle(heading).textAlign!=="center")
       problems.push(id+" column heading must be centered: "+heading.textContent.trim());
     const clip=heading.querySelector(".cl");
     if(!clip||clip.textContent!==heading.textContent||getComputedStyle(heading).whiteSpace!=="nowrap")
       problems.push(id+" heading must retain its full text in a one-line ellipsis container");
   }
   const tickers=rows.map(row=>{
     const cell=row.cells[tickerColumn],link=cell&&cell.querySelector("a");
     if(!link){problems.push(id+" is missing a ticker link");return "";}
     const ticker=link.textContent.trim();
     if(key==="new"){
       const label=row.cells[1]?.querySelector("img")?.alt||"";
       if(!["성조기","태극기"].includes(label))
         problems.push("New-security flag lacks a recognizable country label");
       if((label==="성조기"?"US":"KR")!==country)
         problems.push(id+" contains a security from the wrong country");
       return (label==="성조기"?"US":"KR")+":"+ticker;
     }
     return ticker;
   });
   if(key==="new"){
     counts.new=counts.new||{expected:0,visible:0};
     counts.new.expected+=wanted.length;counts.new.visible+=rows.length;
   }else counts[key]={expected:wanted.length,visible:rows.length};
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
 const returns=document.getElementById("returns");
 const newIds=["new-kr","new-us"],newTables=newIds.map(id=>document.getElementById(id)).filter(Boolean);
 if(document.getElementById("new")||Array.from(document.querySelectorAll(".new-table")).some(table=>!newIds.includes(table.id)))
   problems.push("New securities must use separate Korean and US tables");
 for(const table of newTables)
   if(returns&&!(table.compareDocumentPosition(returns)&Node.DOCUMENT_POSITION_FOLLOWING))
     problems.push("Each country's new-security list must precede ETF returns");
 if(newTables.length===2&&!(newTables[0].compareDocumentPosition(newTables[1])&Node.DOCUMENT_POSITION_FOLLOWING))
   problems.push("The Korean new-security table must precede the US table");
 const allNew=newIds.flatMap(id=>getRows(id).map(row=>(id==="new-kr"?"KR:":"US:")+row.cells[2]?.textContent.trim()));
 if(JSON.stringify(allNew)!==JSON.stringify(expected.new))
   problems.push("The combined new-security inventory or country order differs from the manifest");
 const allHeaders=Array.from(document.querySelectorAll("th")).map(cell=>cell.textContent).join(" ");
 if(allHeaders.includes("현재가"))problems.push("Current-price column remains");
 if(document.body.textContent.includes("첨부"))problems.push("Attachment-related copy remains");
 if(returns){
   const headings=Array.from(returns.querySelectorAll("thead th")).map(cell=>cell.textContent.trim());
   if(headings.length!==16||!/업종|투자/.test(headings[4])||!headings[9].includes("누적")||
      headings[10]!=="최초주가"||headings[11]!=="최근주가"||
      !headings[12].includes("연평균")||!/AUM|시총/.test(headings[13])||
      !headings[14].includes("설립")||!/연수|기간/.test(headings[15]))
     problems.push("ETF columns must include area beside name, cumulative → initial price → latest price → lifetime CAGR → KRW AUM → inception → elapsed years");
 }
 const number=text=>{
   const cleaned=String(text||"").replace(/[^\deE.+-]/g,"");
   return cleaned&&cleaned!=="-"?Number(cleaned):NaN;
 };
 const dateIn=cell=>{
   const labels=[cell?.getAttribute("title")||"",...Array.from(cell?.querySelectorAll("[title]")||[]).map(node=>node.title)];
   const found=labels.join(" ").match(/\d{4}-\d{2}-\d{2}/);
   return found?Date.parse(found[0]+"T00:00:00Z"):NaN;
 };
 const priceTitles=cell=>[cell?.getAttribute("title")||"",...Array.from(cell?.querySelectorAll("[title]")||[]).map(node=>node.title)];
 const exactPriceIn=cell=>{
   const values=priceTitles(cell).map(title=>title.match(/정확값\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)/)).filter(Boolean).map(match=>Number(match[1]));
   return values.length&&values.every(value=>Number.isFinite(value)&&value===values[0])?values[0]:NaN;
 };
 let previousLifetime=Infinity;
 if(getRows("returns").length>100)problems.push("ETF comparison exceeds the top 100 limit");
 getRows("returns").forEach((row,index)=>{
   const colors=[];
   for(const [column,cls] of [[5,"p1"],[6,"p3"],[7,"p5"],[8,"p10"]]){
     const cell=row.cells[column];
     if(!cell||!cell.classList.contains(cls))
       problems.push("ETF "+index+" is missing "+cls+" on the correct return column");
     if(cell)colors.push(getComputedStyle(cell).color);
   }
   if(new Set(colors).size!==4)problems.push("ETF "+index+" return colors are not distinct");
   const lifetime=number(row.cells[12]?.textContent);
   const years=number(row.cells[15]?.textContent);
   if(!Number.isFinite(lifetime)||lifetime>previousLifetime)
     problems.push("ETF lifetime CAGR must be finite and sorted descending");
   if(!Number.isFinite(years)||years<0)
     problems.push("ETF displayed elapsed years must be nonnegative");
   const initial=exactPriceIn(row.cells[10]),latest=exactPriceIn(row.cells[11]);
   for(const [column,exact] of [[10,initial],[11,latest]]){
     const cell=row.cells[column],visible=cell?.textContent.trim()||"",whole=number(visible);
     const serializationTolerance=Math.max(1e-12,Math.abs(exact)*5e-12);
     if(!Number.isFinite(exact)||exact<=0||!Number.isInteger(whole)||whole<0||
        visible!==whole.toLocaleString("en-US",{useGrouping:true,maximumFractionDigits:0})||
        whole<Math.trunc(exact-serializationTolerance)||whole>Math.trunc(exact+serializationTolerance))
       problems.push("ETF "+index+" price must omit decimals, use comma grouping, and preserve its exact value in the title");
     const title=priceTitles(cell).join(" ");
     if(!/정확값\s+/.test(title)||!/\b(?:USD|KRW)\b/.test(title)||!/(?:Yahoo|네이버)/.test(title))
       problems.push("ETF "+index+" price title must preserve the exact value, currency and provider basis");
   }
   const cumulative=number(row.cells[9]?.textContent);
   // Prices carry 12 significant digits; account only for that bounded
   // serialization error and the returns' one-decimal display rounding.
   const cumulativeTolerance=Math.max(.051,(Math.abs(cumulative)+100)*2e-11);
   if(!(initial>0)||!(latest>0)||!Number.isFinite(cumulative)||
      Math.abs((latest/initial-1)*100-cumulative)>cumulativeTolerance)
     problems.push("ETF "+index+" cumulative return does not match its exact starting and latest prices preserved in titles");
   const start=dateIn(row.cells[10]),end=dateIn(row.cells[11]);
   const inceptionText=row.cells[14]?.textContent.trim()||"";
   const knownInception=/^\d{4}-\d{2}-\d{2}$/.test(inceptionText);
   const inception=knownInception?Date.parse(inceptionText+"T00:00:00Z"):NaN;
   const observedYears=(end-start)/(86400000*365.25);
   if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||
      (knownInception&&(!Number.isFinite(inception)||start<inception))||
      (!knownInception&&!["미확인","-"].includes(inceptionText))||Math.abs(observedYears-years)>.00501)
     problems.push("ETF "+index+" price dates, inception and elapsed years disagree");
   if(Number.isFinite(observedYears)&&observedYears>0&&initial>0&&latest>0&&
      Math.abs((Math.pow(latest/initial,1/observedYears)-1)*100-lifetime)>
        Math.max(.051,(Math.abs(lifetime)+100)*2e-11/observedYears))
     problems.push("ETF "+index+" lifetime CAGR does not match its exact prices and dated interval");
   for(const [column,period] of [[5,1],[6,3],[7,5],[8,10]])
     if(Number.isFinite(number(row.cells[column]?.textContent))&&observedYears+.004<period)
       problems.push("ETF "+index+" reports a "+period+"-year return before that much price history exists");
   previousLifetime=lifetime;
 });
 [...getRows("us"),...getRows("kr"),...getRows("new-kr"),...getRows("new-us")].forEach(row=>{
   for(const column of [7,8]){
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
   if(box.left< -tolerance||box.right>viewport+tolerance)
     problems.push("Row "+index+" exceeds the viewport");
   const tableId=row.closest("table").id;
   for(const [column,cell] of Array.from(row.cells).entries()){
     const style=getComputedStyle(cell),bounds=cell.getBoundingClientRect();
     if(style.whiteSpace!=="nowrap")
       problems.push("Row "+index+" must keep every column on one line: "+column);
     const expectedFont=tableId==="returns"&&column!==14?13:12.35;
     if(Math.abs(parseFloat(style.fontSize)-expectedFont)>.01)
       problems.push("Row "+index+" font differs from the enlarged design: "+style.fontSize);
     if(tableId!=="returns"&&column===4&&Math.abs(bounds.width-126)>tolerance)
       problems.push("Row "+index+" industry column must retain the 126px width");
     if(newIds.includes(tableId)&&column===3){
       const tableWidth=row.closest("table").getBoundingClientRect().width;
       if(Math.abs(bounds.width-tableWidth*.19)>tolerance)
         problems.push("Row "+index+" new-security name column must use 19% of table width");
       const previousNameWidth=tableWidth*.54-168;
       if(previousNameWidth<=0||bounds.width/previousNameWidth<.43||bounds.width/previousNameWidth>.58)
         problems.push("Row "+index+" new-security name column must be approximately half its previous width");
     }
     const aumColumn=tableId==="returns"?13:6;
     if(column===aumColumn&&Math.abs(bounds.width-(tableId==="returns"?96:84))>tolerance)
       problems.push("Row "+index+" AUM column must use the restored 96px ETF or 84px stock/new width");
     const clip=cell.querySelector(column===3?".nm":".cl,.iwc");
     if(!clip||clip.textContent!==cell.textContent)
       problems.push("Row "+index+" must retain the entire field in its ellipsis container: "+column);
     if(clip){
       const clipStyle=getComputedStyle(clip),clipBounds=clip.getBoundingClientRect();
       if(clipStyle.display!=="block"||clipStyle.whiteSpace!=="nowrap"||
          clipStyle.overflowX!=="hidden"||clipStyle.textOverflow!=="ellipsis")
         problems.push("Row "+index+" lacks the one-line ellipsis design in column "+column);
       if(clipBounds.left<bounds.left-tolerance||clipBounds.right>bounds.right+tolerance||
          clipBounds.top<bounds.top-tolerance||clipBounds.bottom>bounds.bottom+tolerance)
         problems.push("Row "+index+" ellipsis container exceeds its cell: "+column);
     }
     if(column<row.cells.length-1&&
        (Math.abs(parseFloat(style.borderRightWidth)-1)>.01||style.borderRightStyle!=="solid"||style.borderRightColor!=="rgb(0, 0, 0)")){
       problems.push("Row "+index+" requires a black vertical separator after column "+column);
     }
     const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);let node;
     while((node=walker.nextNode())){
       if(!node.textContent.trim())continue;
       const range=document.createRange();range.selectNodeContents(node);
       const rects=Array.from(range.getClientRects()).filter(rect=>rect.width);
       // Ellipsis can produce visible and hidden rectangles on the same line.
       if(rects.some(rect=>Math.abs(rect.top-rects[0].top)>tolerance)){
         problems.push("Row "+index+" wraps a field: "+node.textContent.trim());
       }
       const intentionalEllipsis=clip&&clip.contains(node);
       for(const rect of rects)
         if((!intentionalEllipsis&&(rect.left<bounds.left-tolerance||rect.right>bounds.right+tolerance))||
            rect.top<bounds.top-tolerance||rect.bottom>bounds.bottom+tolerance)
           problems.push("Row "+index+" clips text: "+node.textContent.trim());
     }
   }
   if(box.height>42)
     problems.push("Row "+index+" is taller than its single-line content: "+box.height);
 });
 for(const row of document.querySelectorAll(".data-table thead tr")){
   for(const [column,cell] of Array.from(row.cells).entries()){
     const clip=cell.querySelector(".cl"),style=getComputedStyle(cell);
     if(clip){
       const clipStyle=getComputedStyle(clip),bounds=cell.getBoundingClientRect(),clipBounds=clip.getBoundingClientRect();
       if(clipStyle.whiteSpace!=="nowrap"||clipStyle.overflowX!=="hidden"||
          clipStyle.textOverflow!=="ellipsis"||clipStyle.textAlign!=="center"||
          clipBounds.left<bounds.left-tolerance||clipBounds.right>bounds.right+tolerance)
         problems.push("A heading lacks a centered and bounded one-line ellipsis: "+cell.textContent.trim());
     }
     if(column<row.cells.length-1&&
        (Math.abs(parseFloat(style.borderRightWidth)-1)>.01||style.borderRightStyle!=="solid"||style.borderRightColor!=="rgb(0, 0, 0)"))
       problems.push("A heading requires a black vertical separator: "+cell.textContent.trim());
   }
 }
 const broken=Array.from(document.images).filter(image=>!image.complete||!image.naturalWidth);
 if(broken.length)problems.push("Broken images: "+broken.map(image=>image.alt).join(","));
 const newNumbering=Object.fromEntries(newIds.map(id=>{
   const rows=getRows(id),numbers=rows.map(row=>row.cells[0]?.textContent.trim());
   return [id==="new-kr"?"kr":"us",{count:rows.length,first:numbers[0]||null,last:numbers[numbers.length-1]||null,
     sequence_valid:numbers.every((value,index)=>value===String(index+1))}];
 }));
 return {
   viewport,counts,new_country_numbering:newNumbering,
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
  "borderTopWidth","borderBottomWidth","borderLeftWidth","borderRightWidth",
  "borderLeftColor","borderRightColor","borderLeftStyle","borderRightStyle",
  "overflowX","textOverflow","verticalAlign"];
 const result={};
 for(const id of ["us","kr","new-kr","new-us","returns"]){
  const table=document.getElementById(id);
  result[id]=table?Array.from(table.rows).map(row=>Array.from(row.cells).map(cell=>{
   const style=getComputedStyle(cell);
   return {tag:cell.tagName,text:cell.textContent.trim(),title:cell.getAttribute("title"),
    titles:Array.from(cell.querySelectorAll("[title]")).map(element=>element.getAttribute("title")),
    links:Array.from(cell.querySelectorAll("a")).map(a=>[a.textContent.trim(),a.getAttribute("href")]),
    flags:Array.from(cell.querySelectorAll("img")).map(img=>[img.getAttribute("src"),img.alt]),
    clipped:Array.from(cell.querySelectorAll(".cl,.nm,.iwc")).map(element=>{
     const clippedStyle=getComputedStyle(element);
     return {text:element.textContent,style:Object.fromEntries(properties.map(key=>[key,clippedStyle[key]]))};
    }),
    style:Object.fromEntries(properties.map(key=>[key,style[key]]))};
  })):[];
 }
 return result;
}"""

NATIVE_CONTENT = r"""() => {
 const result={};
 for(const id of ["us","kr","new-kr","new-us","returns"]){
  const table=document.getElementById(id);
  result[id]=table?Array.from(table.rows).map(row=>Array.from(row.cells).map(cell=>({
   tag:cell.tagName,text:cell.textContent.trim(),title:cell.getAttribute("title"),
   titles:Array.from(cell.querySelectorAll("[title]")).map(element=>element.getAttribute("title")),
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
                    visible=link.evaluate("""element=>{
                      const link=element.getBoundingClientRect(),cell=element.closest('td').getBoundingClientRect();
                      const clip=element.closest('.cl')?.getBoundingClientRect()||cell;
                      return {left:Math.max(link.left,cell.left,clip.left),right:Math.min(link.right,cell.right,clip.right),
                              top:Math.max(link.top,cell.top,clip.top),bottom:Math.min(link.bottom,cell.bottom,clip.bottom)};
                    }""")
                    if visible["right"]<=visible["left"] or visible["bottom"]<=visible["top"]:
                        raise AssertionError("A native US ticker link has no visible clickable text")
                    displayed.mouse.click((visible["left"]+visible["right"])/2,
                                          (visible["top"]+visible["bottom"])/2)
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
                        ("new-kr","email-actual-native-new-kr.png","PREVIEW_IMAGE_ACTUAL_DELIVERY_NEW_KR"),
                        ("new-us","email-actual-native-new-us.png","PREVIEW_IMAGE_ACTUAL_DELIVERY_NEW_US"),
                        ("returns","email-actual-native-etf.png","PREVIEW_IMAGE_ACTUAL_DELIVERY_ETF"),
                    ):
                        cropped_table_image(displayed,table_id,output/filename,marker)
                    if displayed.locator("#us tbody tr").count() and displayed.locator("#kr tbody tr").count():
                        kr_rows=displayed.locator("#kr tbody tr")
                        first_comparison_row=kr_rows.nth(max(0,kr_rows.count()-3))
                        first_comparison_row.evaluate("element=>element.scrollIntoView({block:'start'})")
                        kr=first_comparison_row.bounding_box()
                        us_rows=displayed.locator("#us tbody tr")
                        us=us_rows.nth(min(4,us_rows.count()-1)).bounding_box()
                        section=displayed.locator("#us").bounding_box()
                        viewport=displayed.viewport_size
                        clip={"x":max(0,section["x"]),"y":max(0,kr["y"]),
                              "width":min(section["width"],viewport["width"]-max(0,section["x"])),
                              "height":min(us["y"]+us["height"],viewport["height"])-max(0,kr["y"])}
                        if clip["width"]<=0 or clip["height"]<=0:
                            raise AssertionError("Native font comparison target lies outside the viewport")
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
    size = native_email.validate_source_size(source)
    print("PREVIEW_HTML_BYTES:%d" % size, flush=True)
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
                            new_numbering = result["new_country_numbering"]
                            print("NEW_COUNTRY_NUMBERING:" + json.dumps(new_numbering, ensure_ascii=False), flush=True)
                            for table_id, filename, marker in (
                                ("returns", "email-desktop-etf.png", "PREVIEW_IMAGE_DESKTOP_ETF"),
                                ("new-kr", "email-desktop-new-kr.png", "PREVIEW_IMAGE_DESKTOP_NEW_KR"),
                                ("new-us", "email-desktop-new-us.png", "PREVIEW_IMAGE_DESKTOP_NEW_US"),
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
        "new_country_numbering":new_numbering,"exact_price_titles_checked":True,
    }
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PREVIEW_PASSED:%s" % json.dumps(proof, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()

