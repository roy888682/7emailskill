#!/usr/bin/env python3
"""Render representative or actual email HTML and check narrow-screen geometry."""
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
                         "cumulative_return": round(1280.43 - rank * 44.21, 2),
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
    return render_email(**sample_data())

LAYOUT_CHECK = """() => {
 const tolerance=1.5, viewport=window.innerWidth, problems=[];
 if(document.documentElement.scrollWidth>viewport+tolerance)
   problems.push("document overflow: "+document.documentElement.scrollWidth+" > "+viewport);
 const periods=["1y","3y","5y","10y","cumulative"];
 const cards=Array.from(document.querySelectorAll(".etf-card[data-ticker]"));
 if(!cards.length)problems.push("ETF cards were not rendered");
 cards.forEach((card,index)=>{
  const bounds=card.getBoundingClientRect();
  if(bounds.left< -tolerance||bounds.right>viewport+tolerance)problems.push("ETF "+index+" exceeds viewport width");
  periods.forEach(period=>{
   const metric=card.querySelector('[data-period="'+period+'"]');
   if(!metric){problems.push("ETF "+index+" missing metric "+period);return;}
   const box=metric.getBoundingClientRect(),style=getComputedStyle(metric);
   if(!box.width||!box.height||style.display==="none"||style.visibility==="hidden"||!metric.textContent.trim())
     problems.push("ETF "+index+" metric "+period+" hidden");
   if(box.left<bounds.left-tolerance||box.right>bounds.right+tolerance)
     problems.push("ETF "+index+" metric "+period+" exceeds card");
   const walker=document.createTreeWalker(metric,NodeFilter.SHOW_TEXT);let node;
   while((node=walker.nextNode())){
    if(!node.textContent.trim())continue;
    const range=document.createRange();range.selectNodeContents(node);
    for(const rect of range.getClientRects())
      if(rect.width&&(rect.left<bounds.left-tolerance||rect.right>bounds.right+tolerance))
        problems.push("ETF "+index+" text "+period+" overflows: "+node.textContent.trim());
   }
  });
 });
 return {viewport,cards:cards.length,problems};
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
            for width in (320, 375, 680):
                page = browser.new_page(viewport={"width": width, "height": 1700}, device_scale_factor=1)
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
                if width in (320, 680):
                    name = "mobile" if width == 320 else "desktop"
                    png = page.screenshot(path=str(args.output / ("email-" + name + ".png")), full_page=False)
                    print("PREVIEW_IMAGE_" + name.upper() + ":" + base64.b64encode(png).decode("ascii"), flush=True)
                    stock_section = page.locator(".stock-section").first
                    if stock_section.count():
                        stock_section.scroll_into_view_if_needed()
                        stock_png = page.screenshot(path=str(args.output / ("email-" + name + "-stocks.png")), full_page=False)
                        print("PREVIEW_IMAGE_" + name.upper() + "_STOCKS:" + base64.b64encode(stock_png).decode("ascii"), flush=True)
                page.close()
        finally:
            browser.close()

if __name__ == "__main__":
    main()
