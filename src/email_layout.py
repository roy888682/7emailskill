"""Fluid email layouts with size-bounded bodies and complete reports."""
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
body{margin:0;background:#eef2f6;color:#17263d;font-family:Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:14px;line-height:1.55}
table{border-collapse:collapse}td{vertical-align:top}a{color:#163b68;text-decoration:none}
.shell{max-width:860px;margin:0 auto;padding:18px 12px}.layout{width:100%;table-layout:fixed}
.hero{background:#11243c;color:#fff;border-radius:12px;padding:12px 16px}
.eyebrow{font-size:10px;font-weight:bold;letter-spacing:2px;color:#8fb6c8;margin:0 0 8px}
.hero .eyebrow{display:none}
.hero h1{font-size:22px;line-height:1.25;letter-spacing:-1px;margin:0 0 8px}
.date{font-size:13px;color:#c5d5e4}.hero .foot{font-size:11px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:8px;margin-top:10px}
.summary{margin-top:10px;background:#fff;border:1px solid #dfe7ef;border-radius:10px;padding:10px 12px}
.summary td{width:50%;padding:0 8px}.count{font-size:20px;font-weight:bold;letter-spacing:-1px}
.market{font-weight:bold;font-size:13px;margin-bottom:3px}.muted{font-size:11px;color:#667a90}
.section{margin-top:18px}.section h2{margin:0;font-size:19px;line-height:1.3;letter-spacing:-.6px}
.intro{font-size:11px;color:#667a90;margin:4px 0 8px}

.etf-comparison{background:#fff;border:1px solid #dce5ee;border-radius:10px}
.etf-row{border-top:1px solid #e3eaf2;padding:0 8px;word-wrap:break-word;word-break:break-word}
.etf-row:first-child{border-top:0}.etf-row:nth-child(even){background:#f7f9fc}
.etf-outer{width:100%;table-layout:fixed}
.etf-outer,.etf-outer>tbody,.etf-line,.etf-identity,.etf-numbers{display:block;width:100%;box-sizing:border-box}
.etf-identity,.etf-numbers{width:auto}
.etf-identity{padding:7px 2px 3px;font-size:12px;line-height:1.45}
.etf-identity img{width:22px;height:auto;margin-right:4px!important}
.rank{display:inline-block;background:#163b68;color:#fff;border-radius:3px;padding:0 4px;font-size:10px;font-weight:bold;margin-right:4px}
.ticker{font-size:12px;font-weight:bold;letter-spacing:.2px;margin-right:4px}
.etf-name{font-size:12px;color:#40566e}.etf-numbers{padding:0 0 6px}
.etf-metrics{width:100%;table-layout:fixed}.etf-metrics td{width:20%;padding:4px 1px;text-align:center;vertical-align:middle}
.etf-metrics .metric-label{display:block;color:#64778b;font-size:10px;line-height:1.4;margin-bottom:2px}
.etf-metrics strong{display:block;font-size:12px;line-height:1.45;letter-spacing:-.3px;word-wrap:break-word;word-break:break-word;font-variant-numeric:tabular-nums}
.etf-metrics .one-year{background:#eaf1fb;border-radius:4px}
.etf-column-head{display:none}.etf-caption{font-size:11px;color:#64778b;margin:6px 0 10px;line-height:1.5}
.etf-details{margin-top:16px;border-top:1px solid #dce5ee;padding-top:12px}
.etf-details h3{font-size:15px;margin:0 0 8px}.etf-detail{font-size:11px;color:#64778b;border-bottom:1px solid #e3eaf2;padding:7px 0;word-break:break-word}
.etf-detail b{color:#40566e}.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}
@media screen and (min-width:600px){
.etf-outer{display:table}.etf-outer>tbody{display:table-row-group}.etf-line{display:table-row}
.etf-identity,.etf-numbers{display:table-cell;vertical-align:middle;padding:4px 2px}
.etf-identity{width:40%;padding-right:10px}.etf-numbers{width:60%}
.etf-metrics .metric-label{display:none}.etf-metrics strong{font-size:13px}
.etf-metrics td{padding:2px 2px}
.etf-column-head{display:block;background:#11243c;color:#fff;padding:0 8px;border-radius:9px 9px 0 0}
.etf-column-head .etf-identity{font-size:11px;color:#d4e1ee}
.etf-column-head .etf-metrics td{font-size:11px;color:#d4e1ee}
.etf-column-head .one-year{background:#2b4665;color:#fff}
}
.new-summary{background:#e8f0f8;border-radius:12px;padding:16px;margin-top:18px}
.new-summary h3{font-size:15px;margin:0 0 8px}.new-summary td{width:50%;font-size:13px}
.new{background:#e6f3ed;color:#237353;border-radius:4px;padding:1px 5px;font-size:10px;font-weight:bold}
.stocks{background:#fff;border:1px solid #dce5ee;border-radius:12px;padding:4px 12px}
.stocks td{padding:8px 0;border-bottom:1px solid #eaf0f5;word-break:break-word;word-wrap:break-word}
.stocks tr:last-child td{border-bottom:0}.stock-name{padding-right:12px!important}
.stock-name a{display:block;font-size:13px;font-weight:bold;line-height:1.45}
.stock-name small{display:block;color:#667a90;font-size:11px;line-height:1.6;margin-top:4px}
.stock-values{width:112px;text-align:right}.stock-values b{font-size:13px;display:block}.stock-values small{display:block;font-size:11px}
.notice{background:#fff4dc;color:#796438;border-radius:8px;padding:10px 12px;font-size:12px;margin:12px 0}
.report-note{padding:12px;background:#e8f0f8;border-radius:8px;color:#405d7a;font-size:12px}
.notes{font-size:10px;line-height:1.7;color:#75869a;margin:14px 0}.footer{text-align:center;color:#8a9aab;font-size:10px;padding:24px 0 12px}
@media screen and (max-width:420px){.shell{padding:8px 6px}.hero{padding:12px 14px}.hero h1{font-size:22px}.hero .eyebrow{display:none}.summary{padding:8px 6px}.summary td{padding:0 5px}.count{font-size:22px}.stock-values{width:100px}}
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
    if not value: return "-"
    if value < .1: return f"{value * 1e4:,.0f}억"
    return f"{value:,.2f}조" if value < 10 else f"{value:,.1f}조"

def compact_metric(period, label, value):
    # The shared percent unit keeps five columns legible on a 320px screen.
    number = pct(value).replace("+", "").replace("%", "")
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
    column_head = ('<div class="etf-column-head"><table role="presentation" class="etf-outer">'
                   '<tr class="etf-line"><td class="etf-identity" width="40%">순위 · 국가 · 종목</td>'
                   '<td class="etf-numbers" width="60%"><table role="presentation" class="etf-metrics"><tr>' +
                   "".join(f'<td class="{"one-year" if period == "1y" else ""}">{label}</td>'
                           for period, label, _ in labels) +
                   '</tr></table></td></tr></table></div>')
    lines = []
    for rank, row in enumerate(rows, 1):
        country = "US" if row.get("market") == "US" else "KR"
        ticker = h(row.get("ticker"))
        lines.append(
            f'<div class="etf-row" data-ticker="{ticker}">'
            '<table role="presentation" class="etf-outer"><tr class="etf-line">'
            f'<td class="etf-identity">{flag_html(country)}<span class="rank">{rank:02d}</span>'
            f'<a href="{safe_url(row.get("url"))}"><b class="ticker">{ticker}</b>'
            f'<span class="etf-name">{h(row.get("name"))}</span></a></td>'
            '<td class="etf-numbers"><table role="presentation" class="etf-metrics"><tr>' +
            "".join(f'<td class="{"one-year" if period == "1y" else ""}">'
                    f'{compact_metric(period, label, row.get(key))}</td>'
                    for period, label, key in labels) +
            '</tr></table></td></tr></table></div>')
    notes = ('<p class="notes">ATH -10% 이내 비채권 ETF 기준. 1년 이력이 없는 ETF는 순위에서 제외합니다. '
             '기간 이력이 부족하면 -로 표시합니다.<br>'
             '설립 이래 누적수익률은 수집 가능한 최초 거래일 종가 대비 최신 종가의 전체 상승률이며, 연환산하지 않음.<br>'
             '한국 ETF는 분배금 미반영 가격수익률, 미국 ETF는 배당 재투자 반영 수정주가 기준입니다.</p>')
    details = ""
    if include_details:
        details = '<div class="etf-details"><h3>ETF 상세정보</h3>'
        for rank, row in enumerate(rows, 1):
            details += (f'<div class="etf-detail"><b>{rank:02d} · {h(row.get("ticker"))} · {h(row.get("name"))}</b><br>'
                        f'추종지수 {h(row.get("etf_index"))} · ETF 성격 {h(row.get("etf_kind"))}<br>'
                        f'운용사 {h(row.get("issuer"))} · AUM {aum(row.get("aum") or row.get("mcap"))} · '
                        f'설립일 {h(row.get("inception") or row.get("first_date"))}</div>')
        details += ('<p class="notes">설립일은 운용사 공시값을 우선하고 없으면 최초 거래일, '
                    '운용사는 미확인 시 브랜드로 추정합니다.</p></div>')
    else:
        details = '<p class="muted">추종지수·ETF 성격·운용사·AUM·설립일은 첨부 리포트의 ETF 상세정보에서 확인하세요.</p>'
    return head + '<div class="etf-comparison">' + column_head + "".join(lines) + '</div>' + notes + details + "</div>"

def new_summary(new_us, new_kr):
    return ('<div class="new-summary"><h3>오늘의 신규 등장</h3>'
            '<table role="presentation" class="layout"><tr>'
            f'<td>{flag_html("KR")}<b>{len(new_kr)}</b> 종목</td>'
            f'<td>{flag_html("US")}<b>{len(new_us)}</b> 종목</td>'
            '</tr></table><div class="muted" style="margin-top:6px">'
            '신규 종목은 아래 목록에 신규 배지로 표시합니다. 누적일수는 과거 재등장을 포함합니다.'
            '</div></div>')

def stocks_table(stocks, title, currency, holiday, date_s, hmsg="", new_tickers=None):
    country = "US" if currency == "USD" else "KR"
    new_tickers = set(new_tickers or [])
    head = (f'<div class="section stock-section"><h2>{flag_html(country)}{h(title)}</h2>'
            f'<p class="intro">{len(stocks)}종목 · 기준일 {h(date_s)} · ATH 괴리율 -10%에 가까운 순</p>')
    banner = f'<div class="notice">{h(hmsg)}</div>' if holiday and hmsg else ""
    if not stocks:
        return head + banner + '<p class="muted">해당 종목 없음</p></div>'
    rows = []
    for s in stocks:
        ticker, name = h(s.get("ticker")), h(s.get("name"))
        label = ticker if name == ticker else f"{ticker} · {name}"
        new = ' <span class="new">신규</span>' if s.get("ticker") in new_tickers else ""
        price = s.get("price", 0)
        price_s = "$" + f"{price:,.2f}" if currency == "USD" else f"{price:,}원"
        badges = " · ".join(str(x) for x in s.get("index", []) if x not in ("US", "KR"))
        details = " · ".join(filter(None, [str(s.get("asset_type", "주식")), str(s.get("industry") or "-"), badges]))
        rows.append('<tr><td class="stock-name">'
                    f'<a href="{safe_url(s.get("url"))}">{label}{new}</a>'
                    f'<small>{h(details)}<br>시총 {aum(s.get("mcap"))} · 누적 {s.get("streak", 1)}일째</small>'
                    '</td><td class="stock-values">'
                    f'<b>{price_s}</b><small>일간 {pct(s.get("change", 0))}</small>'
                    f'<small>ATH {pct(s.get("gap", 0))}</small></td></tr>')
    return head + banner + '<div class="stocks"><table class="layout"><tbody>' + "".join(rows) + "</tbody></table></div></div>"

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
                 indices=None, etf_info=None, include_all=False):
    new_us, new_kr = new_us or [], new_kr or []
    indices, etf_info = indices or {}, etf_info or {}
    date_label = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y.%m.%d")
    header = ('<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1">'
              f'<style>{CSS}</style></head><body>'
              '<div style="display:none;max-height:0;opacity:0">ETF 수익률 랭킹과 오늘의 ATH 후보</div>'
              '<div class="shell"><div class="hero"><p class="eyebrow">DAILY MARKET NOTE</p>'
              f'<h1>오늘의 ATH &amp; ETF</h1><div class="date">{date_label} · 일일 시장 리포트</div>'
              f'<div class="foot">All Time High −10% 이내 · 원/달러 {usd_krw:,.0f}원</div></div>')
    prefix = header + _summary(us, kr, info, indices) + etf_section_html(etf_info, include_details=include_all) + new_summary(new_us, new_kr)
    footer = '<div class="footer">일일 ATH 리포트 · 가격 이력 기준 · 투자 권유 아님</div></div></body></html>'
    us_count, kr_count = len(us), len(kr)
    while True:
        reduced = us_count < len(us) or kr_count < len(kr)
        note = (f'<p class="report-note">전체 {len(us) + len(kr)}종목 중 본문 {us_count + kr_count}종목을 표시합니다. '
                '전체 목록은 첨부 리포트에서 확인하세요.</p>') if reduced else ""
        html = (prefix + note
                + stocks_table(kr[:kr_count], "한국 ATH 후보", "KRW", info.get("kr_holiday", False),
                               info.get("kr_last_str", "-"), info.get("kr_holiday_msg", ""),
                               [s.get("ticker") for s in new_kr])
                + stocks_table(us[:us_count], "미국 ATH 후보", "USD", info.get("us_holiday", False),
                               info.get("us_last_str", "-"), info.get("us_holiday_msg", ""),
                               [s.get("ticker") for s in new_us])
                + footer)
        html = re.sub(r">\s+<", "><", html).strip()
        if include_all or len(html.encode("utf-8")) <= MAX_BODY_BYTES:
            return html
        if us_count == 0 and kr_count == 0:
            raise ValueError("ETF section alone exceeds safe email body size")
        if us_count >= kr_count and us_count:
            us_count = max(0, us_count - max(1, us_count // 5))
        else:
            kr_count = max(0, kr_count - max(1, kr_count // 5))
