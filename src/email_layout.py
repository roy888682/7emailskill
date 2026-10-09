"""Dense desktop email tables with protected new-stock lists and bounded bodies."""
import math
import re
from datetime import datetime
from html import escape
import pytz
if __package__:
    from .email_flags import flag_html
else:
    from email_flags import flag_html

MAX_BODY_BYTES = 85000
CSS = """
body{margin:0;background:#f2f5f8;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.4}
table{border-collapse:collapse}a{color:#1260ad;text-decoration:none}
.shell{max-width:1360px;margin:0 auto;padding:12px;color:#17263d;background:#f2f5f8;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.4}.layout{width:100%;table-layout:fixed}
.hero{background:#11243c;color:#fff;border-radius:9px;padding:12px 16px}.hero .eyebrow{display:none}
.hero h1{font-size:19px;line-height:1.2;margin:0 0 5px}.date{font-size:11px;color:#c5d5e4}
.hero .foot{font-size:10px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:6px;margin-top:7px}
.summary{margin-top:8px;background:#fff;border:1px solid #dfe7ef;border-radius:8px;padding:8px 10px}
.summary td{width:50%;padding:0 6px;vertical-align:top}.count{font-size:17px;font-weight:bold}
.market{font-weight:bold;font-size:11px;margin-bottom:2px}.muted{font-size:10px;color:#667a90}
.section{margin-top:14px}.section h2{margin:0;font-size:16px;line-height:1.25}
.intro,.etf-caption{font-size:10px;color:#64778b;margin:4px 0 7px}
.data-table{width:100%;table-layout:auto;background:#fff;border:1px solid #dce5ee;font-size:9.5px;line-height:1.25}
.data-table th,.data-table td{white-space:nowrap;padding:3px 3px;text-align:left;vertical-align:middle}
.data-table th{background:#163b68;color:#fff;font-weight:bold;font-size:10px}
.stock-table th{background:#ee990b;color:#fff}
.asset{display:inline-block;border-radius:3px;padding:1px 4px;font-size:9px;font-weight:bold}.s{background:#dff3ee;color:#087569}.e{background:#eee5fa;color:#753caf}
.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}
.data-table .n{text-align:right;font-variant-numeric:tabular-nums}
.data-table .f{text-align:center;padding-left:3px;padding-right:3px}.f img{width:20px;height:auto;vertical-align:middle}
.data-table .t{font-weight:bold}.data-table .y{background:#eaf1fb;font-weight:bold}
.data-table th.y{background:#2b4665;color:#fff}.data-table .d{font-size:9.5px}
.etf-comparison .data-table{font-size:10px}.metric-label{display:none}.m{display:block;font-size:10px;font-weight:bold;line-height:1.25}
.etf-details{margin-top:12px}.etf-details h3{font-size:13px;margin:0 0 6px}
.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}
.new-section{border-top:3px solid #ee990b;padding-top:8px}.new-table th{background:#ee990b}.r{color:#c23932}.data-table .p1{color:#c23932}.data-table .p3{color:#245ba6}.data-table .p5{color:#087d67}.data-table .p10{color:#7944b0}.data-table .z{background:#f6f8fb}
.new{background:#e6f3ed;color:#237353;border-radius:3px;padding:0 3px;margin-left:3px;font-size:8px;font-weight:bold}
.notice{background:#fff4dc;color:#796438;border-radius:6px;padding:8px 10px;font-size:10px;margin:8px 0}
.report-note{padding:8px 10px;background:#e8f0f8;border-radius:6px;color:#405d7a;font-size:10px}
.notes{font-size:9px;line-height:1.5;color:#75869a;margin:8px 0}.footer{text-align:center;color:#8a9aab;font-size:9px;padding:16px 0 8px}
"""

def h(value):
    return escape(str(value if value is not None else "-"), quote=True)

def safe_url(value):
    value = str(value or "#")
    return h(value if value.startswith(("https://", "http://")) else "#")

def pct(value):
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return '<span class="flat">-</span>'
    state = "up" if value > 0 else "down" if value < 0 else "flat"
    return f'<span class="{state}">{value:+.1f}%</span>'

def aum(value):
    """Input is already KRW trillions; never apply FX in the renderer."""
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return "-"
    if value < 1:
        return f"{value * 1e4:,.0f}억원"
    return f"{value:,.2f}조원" if value < 10 else f"{value:,.1f}조원"

def row_size(row):
    value = row.get("aum") if row.get("asset_type") == "ETF" else None
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        value = row.get("mcap")
    return aum(value)

def signal_pct(value):
    return pct(value).replace('class="up"', 'class="signal-red" style="color:#c23932"').replace(
        'class="down"', 'class="signal-red" style="color:#c23932"').replace(
        'class="flat"', 'class="signal-red" style="color:#c23932"')

def industry_text(row):
    if row.get("asset_type") == "ETF":
        area = row.get("investment_area")
        if area:
            return str(area)
        kind = row.get("etf_kind")
        return f"{kind} (명칭 기준)" if kind else "투자분야 미확인"
    return row.get("industry") or "미확인"


def flag_icon(market):
    """Small drawn PNG flags for dense desktop table cells."""
    icon = re.sub(r' style="[^"]*"', "", flag_html(market))
    return icon.replace('width="30"', 'width="20"').replace('height="16"', 'height="11"').replace('height="20"', 'height="13"')

def inception_text(row):
    value = row.get("inception") or row.get("first_date")
    if not value:
        return "-"
    text = str(value)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else text

def compact_metric(period, label, value):
    number = pct(value).replace("+", "").replace("%", "")
    colors = {"1y": "#c23932", "3y": "#245ba6", "5y": "#087d67", "10y": "#7944b0"}
    if period in colors:
        number = number.replace('class="', f'style="color:{colors[period]}" class="', 1)
    return (f'<div class="metric" data-period="{period}">'
            f'<span class="metric-label">{label}</span><strong>{number}</strong></div>')

def etf_section_html(etf_info, include_details=False):
    rows = etf_info.get("rows", [])
    head = ('<div class="section" id="etf"><h2>ETF 수익률 비교</h2>'
            f'<p class="intro">1년 연평균수익률 내림차순 · 상위 {len(rows)}개'
            f' · 산출 가능 {etf_info.get("with_ret", 0)} / 후보 {etf_info.get("pool", 0)}개</p>'
            '<p class="etf-caption">최근 1·3·5·10년: 연평균수익률(CAGR) · 누적: 설립 이래 누적수익률 · 단위: %</p>')
    if not rows:
        return head + '<p class="muted">해당 ETF 없음</p></div>'
    labels = (("1y", "1년 ↓", "cagr1y"), ("3y", "3년", "cagr3y"),
              ("5y", "5년", "cagr5y"), ("10y", "10년", "cagr10y"),
              ("cumulative", "누적", "cumulative_return"))
    table = ('<div class="etf-comparison"><table class="data-table etf-table" id="returns"><thead><tr>'
             '<th class="number">No.</th><th class="flag-cell">국가</th><th>티커</th><th>종목명</th>' +
             "".join(f'<th class="number {"one-year" if period == "1y" else ""}">{label}</th>'
                     for period, label, _ in labels) +
             '<th class="number" data-field="aum">AUM·시총(원화)</th><th data-field="inception">설립일</th></tr></thead><tbody>')
    for rank, row in enumerate(rows, 1):
        country = "US" if row.get("market") == "US" else "KR"
        ticker = h(row.get("ticker"))
        table += (f'<tr class="etf-row" data-ticker="{ticker}"><td class="number">{rank}</td>'
                  f'<td class="flag-cell">{flag_icon(country)}</td>'
                  f'<td class="ticker-cell"><a href="{safe_url(row.get("url"))}">{ticker}</a></td>'
                  f'<td class="name-cell">{h(row.get("name"))}</td>' +
                  "".join(f'<td class="number {"one-year" if period == "1y" else ""}">'
                          f'{compact_metric(period, label, row.get(key))}</td>'
                          for period, label, key in labels) +
                  f'<td class="number" data-field="aum">{row_size(dict(row, asset_type="ETF"))}</td>'
                  f'<td class="date-cell" data-field="inception">{h(inception_text(row))}</td></tr>')
    table += '</tbody></table></div>'
    notes = ('<p class="notes">ATH -10% 이내 비채권 ETF 기준. 1년 이력이 없는 ETF는 순위에서 제외합니다. '
             '기간 이력이 부족하면 -로 표시합니다.<br>'
             '설립 이래 누적수익률은 수집 가능한 최초 거래일 종가 대비 최신 종가의 전체 상승률이며, 연환산하지 않음.<br>'
             '한국 ETF는 분배금 미반영 가격수익률, 미국 ETF는 배당 재투자 반영 수정주가 기준입니다.<br>'
             '설립일은 운용사 공시값을 우선하고, 없으면 수집 가능한 최초 거래일을 표시합니다. AUM 우선, 없으면 시총을 원화로 표시합니다.</p>')
    details = ""
    if include_details:
        details = ('<div class="etf-details"><h3>ETF 상세정보</h3><table class="data-table">'
                   '<thead><tr><th class="number">No.</th><th>티커</th><th>종목명</th><th>추종지수</th><th>ETF 성격</th>'
                   '<th>운용사</th><th class="number">AUM</th><th>설립일</th></tr></thead><tbody>')
        for rank, row in enumerate(rows, 1):
            details += (f'<tr><td class="number">{rank}</td><td>{h(row.get("ticker"))}</td><td>{h(row.get("name"))}</td>'
                        f'<td>{h(row.get("etf_index"))}</td><td>{h(row.get("etf_kind"))}</td>'
                        f'<td>{h(row.get("issuer"))}</td><td class="number">{aum(row.get("aum") or row.get("mcap"))}</td>'
                        f'<td>{h(inception_text(row))}</td></tr>')
        details += ('</tbody></table><p class="notes">운용사는 미확인 시 브랜드로 추정합니다.</p></div>')
    else:
        details = ""
    return head + table + notes + details + "</div>"

def _stock_row(row, country, new=False, compact=False, number=1):
    ticker = h(row.get("ticker"))
    asset = row.get("asset_type", "주식")
    kind = "etf" if asset == "ETF" else "stock"
    badges = " · ".join(str(x) for x in row.get("index", []) if x not in ("US", "KR")) or "-"
    new_badge = '<span class="new">신규</span>' if new and not compact else ""
    cls = "new-row" if compact else "stock-row"
    source = h(row.get("investment_area_source") or "업종 데이터")
    cells = (f'<tr class="{cls}" data-ticker="{ticker}" data-key="{country}:{ticker}">'
             f'<td class="number">{number}</td>'
             f'<td class="flag-cell">{flag_icon(country)}</td>'
             f'<td class="ticker-cell"><a href="{safe_url(row.get("url"))}">{ticker}</a>{new_badge}</td>'
             f'<td class="name-cell">{h(row.get("name"))}</td>'
             f'<td><span class="asset asset-{kind}">{h(asset)}</span></td>'
             f'<td class="number" data-field="size">{row_size(row)}</td>'
             f'<td class="number" data-field="gap">{signal_pct(row.get("gap"))}</td>'
             f'<td title="{source}">{h(industry_text(row))}</td>'
             f'<td class="number" data-field="change">{signal_pct(row.get("change"))}</td>'
             f'<td class="number">{h(row.get("streak", 1))}일째</td>')
    return cells + ("" if compact else f'<td>{h(badges)}</td>') + "</tr>"

def _stock_head(compact=False):
    return ('<thead><tr><th class="number">No.</th><th class="flag-cell">국가</th><th>티커</th><th>종목명</th><th>구분</th>'
            '<th class="number">시총·AUM(원화)</th><th class="number">ATH 괴리율</th>'
            '<th>업종·투자분야</th><th class="number">전일 등락률</th><th class="number">누적일수</th>' +
            ("" if compact else "<th>지수</th>") + "</tr></thead><tbody>")

def new_summary(new_us, new_kr, totals=None, offset=0):
    """All new securities are a dedicated visible list, never count-only badges."""
    total_kr, total_us = totals or (len(new_kr), len(new_us))
    count = len(new_us) + len(new_kr)
    overall = total_kr + total_us
    note = (f" · 전체 {overall}개 중 {offset + 1}~{offset + count}번째" if count < overall else "")
    head = (f'<div class="section new-section" id="new-stocks" data-total="{overall}" data-shown="{count}">'
            f'<h2>오늘의 신규 등장 · 한국 {total_kr} · 미국 {total_us}{note}</h2>'
            '<p class="intro">직전 거래일에 없던 종목 · 누적일수는 과거 재등장을 포함합니다.</p>')
    if not count:
        return head + '<p class="muted">오늘의 신규 등장 종목이 없습니다.</p></div>'
    numbered = [(country, row) for country, items in (("KR", new_kr), ("US", new_us)) for row in items]
    rows = "".join(_stock_row(row, country, compact=True, number=number)
                   for number, (country, row) in enumerate(numbered, offset + 1))
    return head + '<table class="data-table new-table" id="new">' + _stock_head(True) + rows + '</tbody></table></div>'

def stocks_table(stocks, title, currency, holiday, date_s, hmsg="", new_tickers=None):
    country = "US" if currency == "USD" else "KR"
    new_tickers = set(new_tickers or [])
    head = (f'<div class="section stock-section"><h2>{flag_html(country)}{h(title)}</h2>'
            f'<p class="intro">{len(stocks)}종목 · 기준일 {h(date_s)} · ATH 괴리율 -10%에 가까운 순</p>')
    banner = f'<div class="notice">{h(hmsg)}</div>' if holiday and hmsg else ""
    if not stocks:
        return head + banner + '<p class="muted">해당 종목 없음</p></div>'
    table = f'<table class="data-table stock-table" id="{country.lower()}">' + _stock_head()
    table += "".join(_stock_row(row, country, row.get("ticker") in new_tickers, number=number)
                     for number, row in enumerate(stocks, 1))
    return head + banner + table + '</tbody></table></div>'

def _summary(us, kr, info, indices):
    def value(key):
        v = indices.get(key)
        return f"{v:,.1f}" if v else "-"
    return ('<div class="summary"><table role="presentation" class="layout"><tr><td>'
            f'<div class="market">{flag_html("KR")}한국 <span class="count">{len(kr)}<span style="font-size:12px"> 종목</span></span></div>'
            f'<div class="muted">KOSPI {value("kospi")} {pct(indices.get("kospi_chg"))}<br>{h(info.get("kr_last_str"))}</div>'
            '</td><td>'
            f'<div class="market">{flag_html("US")}미국 <span class="count">{len(us)}<span style="font-size:12px"> 종목</span></span></div>'
            f'<div class="muted">S&amp;P 500 {value("sp500")} {pct(indices.get("sp500_chg"))}<br>{h(info.get("us_last_str"))}</div>'
            '</td></tr></table></div>')

def render_email(us, kr, info, usd_krw, new_us=None, new_kr=None, diag=None,
                 indices=None, etf_info=None, compact=True):
    """Render every candidate with the existing desktop layout."""
    new_us, new_kr = new_us or [], new_kr or []
    indices, etf_info = indices or {}, etf_info or {}
    date_label = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y.%m.%d")
    styles = "".join(line.strip() for line in CSS.splitlines())
    header = ('<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<style>{styles}</style></head><body>'
              '<div class="shell"><div class="hero">'
              f'<h1>오늘의 ATH &amp; ETF</h1><div class="date">{date_label} · 일일 시장 리포트</div>'
              f'<div class="foot">All Time High −10% 이내 · 원/달러 {usd_krw:,.0f}원</div></div>')
    html = (header + _summary(us, kr, info, indices) + new_summary(new_us, new_kr)
            + etf_section_html(etf_info, include_details=False)
            + '<p class="notes">업종·투자분야: 주식은 기업 업종, ETF는 제공업체 분류를 표시합니다. 분류가 없으면 명칭 기준으로 표시합니다.</p>'
            + stocks_table(kr, "한국 ATH 후보", "KRW", info.get("kr_holiday", False),
                           info.get("kr_last_str", "-"), info.get("kr_holiday_msg", ""),
                           [s.get("ticker") for s in new_kr])
            + stocks_table(us, "미국 ATH 후보", "USD", info.get("us_holiday", False),
                           info.get("us_last_str", "-"), info.get("us_holiday_msg", ""),
                           [s.get("ticker") for s in new_us])
            + '<div class="footer">일일 ATH 리포트 · 가격 이력 기준 · 투자 권유 아님</div></div></body></html>')
    return delivery_html(html, compact=compact)



def delivery_html(source, compact=True):
    """Reduce invisible markup while preserving the restored table alignment."""
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(source, "html5lib")
    aliases = {"number":"n", "flag-cell":"f", "ticker-cell":"t",
               "one-year":"y", "date-cell":"d",
               "asset-etf":"e", "asset-stock":"s"}
    for table in doc.select("table.data-table"):
        for rank, row in enumerate(table.select("tbody tr")):
            row.attrs = {"class":["z"]} if rank % 2 else {}
            for cell in row.find_all("td", recursive=False):
                cell.attrs = {"class":cell.get("class", [])} if cell.get("class") else {}
                metric = cell.find("div", class_="metric")
                if metric:
                    period = metric.get("data-period")
                    value = metric.find("strong").find("span")
                    replacement = doc.new_tag("b")
                    replacement.string = value.get_text()
                    replacement["class"] = ["m"]
                    if period in ("1y","3y","5y","10y"):
                        period_class = {"1y":"p1","3y":"p3","5y":"p5","10y":"p10"}[period]
                        cell["class"] = cell.get("class", []) + [period_class]
                    else:
                        replacement["class"] += value.get("class", [])
                    metric.replace_with(replacement)
                signal = cell.find("span", class_="signal-red")
                if signal:
                    cell["class"] = cell.get("class", []) + ["r"]
                    signal.unwrap()
                for badge in cell.select("span.asset"):
                    badge.name = "b"
                for picture in cell.select("img"):
                    picture.attrs = {"src":picture["src"],"alt":picture.get("alt","")}
    for tag in doc.find_all():
        for key in list(tag.attrs):
            if key.startswith("data-") or key == "title":
                del tag.attrs[key]
        if tag.get("class"):
            tag["class"] = [aliases.get(cls, cls) for cls in tag["class"] if cls not in ("name-cell", "etf-table")]
            if not tag["class"]:
                del tag["class"]
    result = str(doc)
    result = re.sub(r">\s+<", "><", result).strip()
    return compact_transport_html(result) if compact else result


def compact_transport_html(source):
    """Omit only HTML5-optional syntax; the rendered table DOM is unchanged."""
    # These selector aliases apply the very same declarations to shorter
    # class lists. The uncompressed reference is pixel-compared before SMTP.
    result = source.replace(".asset{", ".asset,.e,.s{", 1)
    result = result.replace(".data-table .n{", ".data-table .n,.data-table .r{", 1)
    result = result.replace('class="asset e"', 'class="e"').replace('class="asset s"', 'class="s"')
    result = result.replace('class="n r"', 'class="r"')
    # Every table link is a ticker; inherit the identical bold style directly.
    result = result.replace(".data-table .t{", ".data-table .t,.data-table a{", 1)
    result = result.replace(' class="t"', "")
    # The two badge elements carry the same visual rules without per-row classes.
    result = result.replace(".asset,.e,.s{", ".asset,.e,.s,.stock-table b,.stock-table i,.new-table b,.new-table i{", 1)
    result = result.replace(".s{", ".s,.stock-table b,.new-table b{", 1)
    result = result.replace(".e{", ".e,.stock-table i,.new-table i{", 1)
    result = result.replace("</style>", ".stock-table i,.new-table i{font-style:normal}</style>", 1)
    result = re.sub(r'<b class="s">(.*?)</b>', r'<b>\1</b>', result)
    result = re.sub(r'<b class="e">(.*?)</b>', r'<i>\1</i>', result)
    # Country flags repeat the country heading in these single-country tables.
    # Keep them decorative there and label the table; mixed tables retain alt.
    for country, label in (("us", "미국 종목"), ("kr", "한국 종목")):
        pattern = r'(<table\b[^>]*\bid="' + country + r'"[^>]*>)(.*?)(</table>)'
        def country_table(match):
            head = match.group(1).replace(">", ' aria-label="' + label + '">', 1)
            rows = re.sub(r'\s+alt="[^"]*"', "", match.group(2))
            return head + rows + match.group(3)
        result = re.sub(pattern, country_table, result, flags=re.DOTALL)
    result = re.sub(r"</td>(?=<(?:td|th|/tr))", "", result)
    result = re.sub(r"</th>(?=<(?:td|th|/tr))", "", result)
    result = re.sub(r"</tr>(?=<(?:tr|/thead|/tbody|/tfoot))", "", result)
    result = re.sub(r'="([A-Za-z0-9_:/.,?&;%#+~-]+)"', r"=\1", result)
    result = re.sub(r"(<(?:img|meta|br)\b[^>]*?)/>", r"\1>", result)
    # 8BITMIME preserves UTF-8 without Base64 expansion. Keep SMTP lines
    # below 998 octets using whitespace at block boundaries only.
    result = re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                    lambda match: match.group(1) + match.group(2).replace("}", "}\n") + match.group(3),
                    result, flags=re.DOTALL)
    # Whitespace inside opening tags is invisible even when td end tags are omitted.
    result = re.sub(r"<(tr|table|thead|tbody|div|p|h1|h2|style|br)(?=[\s>])", r"<\1\n", result)
    if max((len(line.encode("utf-8")) for line in result.splitlines()), default=0) > 998:
        raise RuntimeError("HTML exceeds the SMTP line limit; compact markup without removing candidates")
    return result

def inventory(source):
    """Read real table contents with the HTML5 parser, not debug attributes."""
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(source, "html5lib")
    def tickers(table_id, column):
        table = doc.find("table", id=table_id)
        result = []
        if table:
            for row in table.select("tbody tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) <= column:
                    raise RuntimeError("Malformed report row: " + table_id)
                anchor = cells[column].find("a")
                result.append(str(anchor.contents[0]) if anchor else cells[column].get_text(strip=True))
        return result
    result = {"us": tickers("us", 2), "kr": tickers("kr", 2),
              "etf": tickers("returns", 2), "new": []}
    table = doc.find("table", id="new")
    if table:
        for row in table.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            country = "US" if cells[1].find("img")["src"] == "cid:u" else "KR"
            result["new"].append(country + ":" + str(cells[2].find("a").contents[0]))
    return result


def validate_inventory(source, expected):
    actual = inventory(source)
    if actual != expected:
        raise RuntimeError("Email tables do not exactly match collected candidates")
    return actual


MAX_EMAIL_BYTES = MAX_BODY_BYTES

def validate_size(source):
    size = len(source.encode("utf-8"))
    if size > MAX_EMAIL_BYTES:
        raise RuntimeError(f"Email HTML {size:,} bytes exceeds {MAX_EMAIL_BYTES:,}; compact markup before sending, never remove candidates")
    return size
