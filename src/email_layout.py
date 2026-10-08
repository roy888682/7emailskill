"""Complete desktop email tables: every candidate in one body, no attachments."""
import math
import re
from datetime import datetime
from html import escape
import pytz
if __package__:
    from .email_flags import flag_html
else:
    from email_flags import flag_html

CSS = """
body{margin:0;background:#f2f5f8;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.4}
table{border-collapse:collapse}a{color:#1260ad;text-decoration:none}
.shell{max-width:1360px;margin:0 auto;padding:12px}.layout{width:100%;table-layout:fixed}
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
.asset{display:inline-block;border-radius:3px;padding:1px 4px;font-size:9px;font-weight:bold}.asset-stock{background:#dff3ee;color:#087569}.asset-etf{background:#eee5fa;color:#753caf}
.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}
.data-table .number,.data-table .n{text-align:right;font-variant-numeric:tabular-nums}
.data-table .flag-cell,.data-table .f{text-align:center;padding-left:3px;padding-right:3px}.flag-cell img,.f img{width:20px;height:auto;vertical-align:middle}
.data-table .ticker-cell,.t{font-weight:bold}.data-table .one-year{background:#eaf1fb;font-weight:bold}
.data-table th.one-year{background:#2b4665;color:#fff}.data-table .date-cell{font-size:9.5px}
.etf-comparison .data-table{font-size:10px}.metric{font-size:10px;font-weight:bold;line-height:1.25}
.etf-details{margin-top:12px}.etf-details h3{font-size:13px;margin:0 0 6px}.etf-details .data-table{table-layout:fixed}.etf-details td{white-space:normal;overflow-wrap:anywhere}
.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}.p1{color:#c23932}.p3{color:#245ba6}.p5{color:#087d67}.p10{color:#7944b0}
.new-section{border-top:3px solid #ee990b;padding-top:8px}.new-table th{background:#ee990b}.red{color:#c23932}
.new{background:#e6f3ed;color:#237353;border-radius:3px;padding:0 3px;margin-left:3px;font-size:8px;font-weight:bold}
.notice{background:#fff4dc;color:#796438;border-radius:6px;padding:8px 10px;font-size:10px;margin:8px 0}
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
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "-"
    return f"{value:+.1f}%"

def industry_text(row):
    if row.get("asset_type") == "ETF":
        area = row.get("investment_area")
        if area:
            return str(area)
        kind = row.get("etf_kind")
        return f"{kind} (명칭 기준)" if kind else "투자분야 미확인"
    return row.get("industry") or "미확인"


def flag_icon(market):
    """CID PNGs with compact markup; each image is embedded once in MIME."""
    country = "us" if market == "US" else "kr"
    label = "성조기" if country == "us" else "태극기"
    return f'<img src="cid:ath-flag-{country}" width="20" alt="{label}">'

def inception_text(row):
    value = row.get("inception") or row.get("first_date")
    if not value:
        return "-"
    text = str(value)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else text

def compact_metric(period, label, value):
    valid = isinstance(value, (int, float)) and math.isfinite(value)
    number = f"{value:.1f}" if valid else "-"
    state = "up" if valid and value > 0 else "down" if valid and value < 0 else "flat"
    period_class = {"1y": "p1", "3y": "p3", "5y": "p5", "10y": "p10"}.get(period, "")
    return f'<span class="metric {state} {period_class}" data-period="{period}">{number}</span>'

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
    table = ('<div class="etf-comparison"><table class="data-table etf-table"><thead><tr>'
             '<th class="number">순위</th><th class="flag-cell">국가</th><th>티커</th><th>종목명</th>' +
             "".join(f'<th class="number {"one-year" if period == "1y" else ""}">{label}</th>'
                     for period, label, _ in labels) +
             '<th class="number" data-field="aum">AUM·시총(원화)</th><th data-field="inception">설립일</th></tr></thead><tbody>')
    for rank, row in enumerate(rows, 1):
        country = "US" if row.get("market") == "US" else "KR"
        ticker = h(row.get("ticker"))
        table += (f'<tr class="etf-row" data-ticker="{ticker}"><td class="number">{rank:02d}</td>'
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
                   '<thead><tr><th>티커</th><th>종목명</th><th>추종지수</th><th>ETF 성격</th>'
                   '<th>운용사</th><th class="number">AUM</th><th>설립일</th></tr></thead><tbody>')
        for row in rows:
            details += (f'<tr><td>{h(row.get("ticker"))}</td><td>{h(row.get("name"))}</td>'
                        f'<td>{h(row.get("etf_index"))}</td><td>{h(row.get("etf_kind"))}</td>'
                        f'<td>{h(row.get("issuer"))}</td><td class="number">{aum(row.get("aum") or row.get("mcap"))}</td>'
                        f'<td>{h(inception_text(row))}</td></tr>')
        details += ('</tbody></table><p class="notes">운용사는 미확인 시 브랜드로 추정합니다.</p></div>')
    return head + table + notes + details + "</div>"

def _stock_row(row, country, new=False, compact=False):
    ticker = h(row.get("ticker"))
    asset = row.get("asset_type", "주식")
    kind = "etf" if asset == "ETF" else "stock"
    badges = " · ".join(str(x) for x in row.get("index", []) if x not in ("US", "KR")) or "-"
    new_badge = '<span class="new">신규</span>' if new and not compact else ""
    cls = "new-row" if compact else "stock-row"
    cells = (f'<tr class="{cls}" data-key="{country}:{ticker}">'
             f'<td class="f">{flag_icon(country)}</td>'
             f'<td class="t"><a href="{safe_url(row.get("url"))}">{ticker}</a>{new_badge}</td>'
             f'<td>{h(row.get("name"))}</td><td><span class="asset asset-{kind}">{h(asset)}</span></td>'
             f'<td class="n">{row_size(row)}</td>'
             f'<td class="n red">{signal_pct(row.get("gap"))}</td>'
             f'<td>{h(industry_text(row))}</td>'
             f'<td class="n red">{signal_pct(row.get("change"))}</td>'
             f'<td class="n">{h(row.get("streak", 1))}일째</td>')
    return cells + ("" if compact else f'<td>{h(badges)}</td>') + "</tr>"

def _stock_head(compact=False):
    return ('<thead><tr><th class="flag-cell">국가</th><th>티커</th><th>종목명</th><th>구분</th>'
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
    rows = "".join(_stock_row(row, country, compact=True)
                   for country, items in (("KR", new_kr), ("US", new_us)) for row in items)
    return head + '<table class="data-table new-table">' + _stock_head(True) + rows + '</tbody></table></div>'

def stocks_table(stocks, title, currency, holiday, date_s, hmsg="", new_tickers=None):
    country = "US" if currency == "USD" else "KR"
    new_tickers = set(new_tickers or [])
    head = (f'<div class="section stock-section"><h2>{flag_html(country)}{h(title)}</h2>'
            f'<p class="intro">{len(stocks)}종목 · 기준일 {h(date_s)} · ATH 괴리율 -10%에 가까운 순</p>')
    banner = f'<div class="notice">{h(hmsg)}</div>' if holiday and hmsg else ""
    if not stocks:
        return head + banner + '<p class="muted">해당 종목 없음</p></div>'
    table = f'<table class="data-table stock-table" data-country="{country}" data-count="{len(stocks)}">' + _stock_head()
    table += "".join(_stock_row(row, country, row.get("ticker") in new_tickers) for row in stocks)
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
                 indices=None, etf_info=None):
    """Never slice lists or split messages according to HTML size."""
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
            + etf_section_html(etf_info, include_details=True)
            + '<p class="notes">업종·투자분야: 주식은 기업 업종, ETF는 제공업체 분류를 표시합니다. 분류가 없으면 명칭 기준으로 표시합니다.</p>'
            + stocks_table(kr, "한국 ATH 후보", "KRW", info.get("kr_holiday", False),
                           info.get("kr_last_str", "-"), info.get("kr_holiday_msg", ""),
                           [s.get("ticker") for s in new_kr])
            + stocks_table(us, "미국 ATH 후보", "USD", info.get("us_holiday", False),
                           info.get("us_last_str", "-"), info.get("us_holiday_msg", ""),
                           [s.get("ticker") for s in new_us])
            + '<div class="footer">일일 ATH 리포트 · 가격 이력 기준 · 투자 권유 아님</div></div></body></html>')
    return re.sub(r">\s+<", "><", html).strip()
