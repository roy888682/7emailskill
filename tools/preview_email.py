#!/usr/bin/env python3
"""Render desktop emails and verify one visible line per security."""
import argparse
import base64
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

def build_preview_html():
    from src.email_layout import render_email
    data = sample_data()
    data["new_us"] = data["new_us"][:10]
    return render_email(**data)

LAYOUT_CHECK = """() => {
 const tolerance=1.5,viewport=window.innerWidth,problems=[];
 if(document.documentElement.scrollWidth>viewport+tolerance)
   problems.push("document overflow: "+document.documentElement.scrollWidth+" > "+viewport);
 const periods=["1y","3y","5y","10y","cumulative"];
 const etfs=Array.from(document.querySelectorAll(".etf-row[data-ticker]"));
 const stocks=Array.from(document.querySelectorAll(".stock-row[data-key]"));
 const newRows=Array.from(document.querySelectorAll(".new-row[data-key]"));
 const newSection=document.querySelector("#new-stocks");
 if(!newSection||newRows.length!==Number(newSection.dataset.shown))problems.push("New securities missing from visible list");
 if(document.querySelector("thead")?.textContent.includes("현재가"))problems.push("Current-price column is still displayed");
 if(!etfs.length)problems.push("ETF rows were not rendered");
 const counts={};
 document.querySelectorAll(".stock-table").forEach(table=>{
   const rows=Array.from(table.querySelectorAll("tbody .stock-row"));
   const expected=Number(table.dataset.count),country=table.dataset.country;
   counts[country]={expected,visible:rows.length};
   if(rows.length!==expected)problems.push(country+" candidate count differs from rendered list");
   const keys=rows.map(row=>row.dataset.key);
   if(keys.some(key=>!key.startsWith(country+":")))problems.push(country+" table contains wrong-country rows");
   if(new Set(keys).size!==keys.length)problems.push(country+" table contains duplicate candidates");
   const section=table.closest(".stock-section");
   if(!section.querySelector(".intro").textContent.includes(expected+"종목"))problems.push(country+" heading count differs from rows");
 });
 if(document.body.textContent.includes("첨부"))problems.push("Attachment-related copy remains");
 if(etfs.length&&document.querySelector("#new-stocks").compareDocumentPosition(document.querySelector("#etf"))&Node.DOCUMENT_POSITION_PRECEDING)
   problems.push("New list must precede ETF comparison");
 etfs.forEach((row,index)=>{
   const metrics=periods.map(period=>row.querySelector('[data-period="'+period+'"]'));
   if(metrics.some(metric=>!metric)){problems.push("ETF "+index+" missing a return metric");return;}
   const date=row.querySelector('[data-field="inception"]');
   const cumulative=metrics[4].closest("td");
   const size=row.querySelector('[data-field="aum"]');
   if(!date||!size||cumulative.nextElementSibling!==size||size.nextElementSibling!==date)
     problems.push("ETF "+index+" requires cumulative → KRW AUM → inception");
   const colors=metrics.slice(0,4).map(metric=>getComputedStyle(metric).color);
   if(new Set(colors).size!==4)problems.push("ETF "+index+" return colors are not distinct");
 });
 [...stocks,...newRows].forEach(row=>{
   for(const column of [5,7]){
     const cell=row.cells[column];
     if(!cell||getComputedStyle(cell).color!=="rgb(194, 57, 50)")problems.push("ATH/day change must be red");
   }
 });
 const stockBadge=document.querySelector(".asset-stock"),etfBadge=document.querySelector(".asset-etf");
 if(stockBadge&&etfBadge&&getComputedStyle(stockBadge).backgroundColor===getComputedStyle(etfBadge).backgroundColor)
   problems.push("Stock and ETF badge colors are identical");
 [...etfs,...stocks,...newRows].forEach((row,index)=>{
   const box=row.getBoundingClientRect();
   if(box.height>32)problems.push("Row "+index+" is taller than a single line: "+box.height);
   if(box.left< -tolerance||box.right>viewport+tolerance)problems.push("Row "+index+" exceeds viewport");
   for(const cell of row.cells){
     const bounds=cell.getBoundingClientRect();
     if(getComputedStyle(cell).whiteSpace!=="nowrap")problems.push("Row "+index+" permits wrapping");
     const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT);let node;
     while((node=walker.nextNode())){
       if(!node.textContent.trim())continue;
       const range=document.createRange();range.selectNodeContents(node);
       const rects=Array.from(range.getClientRects()).filter(rect=>rect.width);
       if(rects.length>1)problems.push("Row "+index+" wraps text: "+node.textContent.trim());
       for(const rect of rects)
         if(rect.left<bounds.left-tolerance||rect.right>bounds.right+tolerance)
           problems.push("Row "+index+" text exceeds cell: "+node.textContent.trim());
     }
   }
 });
 return {viewport,etfs:etfs.length,stocks:stocks.length,newRows:newRows.length,counts,
         etfHeight:Math.round(document.querySelector(".etf-table")?.getBoundingClientRect().height||0),problems};
}"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "work")
    args = parser.parse_args()
    from src.email_flags import inline_flag_sources
    from playwright.sync_api import sync_playwright
    source = args.html.read_text(encoding="utf-8") if args.html else build_preview_html()
    html_source = inline_flag_sources(source)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "email-preview.html").write_text(html_source, encoding="utf-8")
    print("PREVIEW_HTML_BYTES:%d" % len(source.encode("utf-8")), flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (1024, 1280, 1600, 1920):
                page = browser.new_page(viewport={"width": width, "height": 1200}, device_scale_factor=1)
                page.set_content(html_source, wait_until="load")
                page.evaluate("document.fonts.ready")
                result = page.evaluate(LAYOUT_CHECK)
                print("LAYOUT_QA:%s" % result, flush=True)
                if result["problems"]:
                    raise AssertionError("; ".join(result["problems"]))
                broken = page.locator("img").evaluate_all(
                    "imgs => imgs.filter(i=>!i.complete||!i.naturalWidth).map(i=>i.alt)")
                if broken:
                    raise AssertionError("Flag images did not load: %s" % broken)
                if width in (1024, 1600):
                    name = "compact" if width == 1024 else "desktop"
                    png = page.screenshot(path=str(args.output / ("email-" + name + ".png")), full_page=False)
                    print("PREVIEW_IMAGE_" + name.upper() + ":" + base64.b64encode(png).decode("ascii"), flush=True)
                    new_section = page.locator("#new-stocks")
                    if new_section.count():
                        new_section.scroll_into_view_if_needed()
                        new_png = page.screenshot(path=str(args.output / ("email-" + name + "-new.png")), full_page=False)
                        print("PREVIEW_IMAGE_" + name.upper() + "_NEW:" + base64.b64encode(new_png).decode("ascii"), flush=True)
                    stock_section = page.locator(".stock-section").first
                    if stock_section.count():
                        stock_section.scroll_into_view_if_needed()
                        stock_png = page.screenshot(path=str(args.output / ("email-" + name + "-stocks.png")), full_page=False)
                        print("PREVIEW_IMAGE_" + name.upper() + "_STOCKS:" + base64.b64encode(stock_png).decode("ascii"), flush=True)
                if width == 1600:
                    last_row = page.locator(".stock-row").last
                    if last_row.count():
                        last_row.scroll_into_view_if_needed()
                        last_png = page.screenshot(path=str(args.output / "email-desktop-last.png"), full_page=False)
                        print("PREVIEW_IMAGE_DESKTOP_LAST:" + base64.b64encode(last_png).decode("ascii"), flush=True)
                page.close()
        finally:
            browser.close()

if __name__ == "__main__":
    main()
