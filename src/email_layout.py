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
.data-table th,.data-table td{white-space:nowrap;padding:3px 4px;text-align:left;vertical-align:middle}
.data-table th{background:#163b68;color:#fff;font-weight:bold;font-size:10px}
.stock-table th{background:#ee990b;color:#fff}
.asset{display:inline-block;background:#e1f4f0;color:#087569;border-radius:3px;padding:1px 4px;font-size:9px}
.data-table td{border-bottom:1px solid #e7edf3}.data-table tbody tr:nth-child(even){background:#f6f8fb}
.data-table .number{text-align:right;font-variant-numeric:tabular-nums}
.data-table .flag-cell{text-align:center;padding-left:3px;padding-right:3px}.flag-cell img{width:20px;height:auto;vertical-align:middle}
.data-table .ticker-cell{font-weight:bold}.data-table .one-year{background:#eaf1fb;font-weight:bold}
.data-table th.one-year{background:#2b4665;color:#fff}.data-table .date-cell{font-size:9.5px}
.etf-comparison .data-table{font-size:10px}.metric-label{display:none}.metric strong{font-size:10px;font-weight:bold;line-height:1.25}
.etf-details{margin-top:12px}.etf-details h3{font-size:13px;margin:0 0 6px}
.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}
.new-summary{background:#fff3df;border-radius:8px;padding:10px 12px;margin-top:14px}
.new-summary h3{font-size:14px;margin:0 0 6px}.new-summary td{width:50%;font-size:11px}
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
    if not value: return "-"
    if value < .1: return f"{value * 1e4:,.0f}억"
    return f"{value:,.2f}조" if value < 10 else f"{value:,.1f}조"

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
    table = ('<div class="etf-comparison"><table class="data-table etf-table"><thead><tr>'
             '<th class="number">순위</th><th class="flag-cell">국가</th><th>티커</th><th>종목명</th>' +
             "".join(f'<th class="number {"one-year" if period == "1y" else ""}">{label}</th>'
                     for period, label, _ in labels) +
             '<th data-field="inception">설립일</th></tr></thead><tbody>')
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
                  f'<td class="date-cell" data-field="inception">{h(inception_text(row))}</td></tr>')
    table += '</tbody></table></div>'
    notes = ('<p class="notes">ATH -10% 이내 비채권 ETF 기준. 1년 이력이 없는 ETF는 순위에서 제외합니다. '
             '기간 이력이 부족하면 -로 표시합니다.<br>'
             '설립 이래 누적수익률은 수집 가능한 최초 거래일 종가 대비 최신 종가의 전체 상승률이며, 연환산하지 않음.<br>'
             '한국 ETF는 분배금 미반영 가격수익률, 미국 ETF는 배당 재투자 반영 수정주가 기준입니다.<br>'
             '설립일은 운용사 공시값을 우선하고, 없으면 수집 가능한 최초 거래일을 표시합니다.</p>')
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
    else:
        details = '<p class="muted">추종지수·ETF 성격·운용사·AUM은 첨부 리포트의 ETF 상세정보에서 확인하세요.</p>'
    return head + table + notes + details + "</div>"

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
    table = ('<table class="data-table stock-table"><thead><tr>'
             '<th class="flag-cell">국가</th><th>티커</th><th>종목명</th><th>구분</th>'
             '<th class="number">시가총액</th><th class="number">ATH 괴리율</th><th>업종</th>'
             '<th class="number">전일 등락률</th><th class="number">현재가</th>'
             '<th class="number">누적일수</th><th>지수</th></tr></thead><tbody>')
    for row in stocks:
        price = row.get("price", 0)
        price_s = f"{price:,.2f} USD" if currency == "USD" else f"{price:,} KRW"
        badges = " · ".join(str(x) for x in row.get("index", []) if x not in ("US", "KR")) or "-"
        new = '<span class="new">신규</span>' if row.get("ticker") in new_tickers else ""
        table += (f'<tr class="stock-row" data-ticker="{h(row.get("ticker"))}">'
                  f'<td class="flag-cell">{flag_icon(country)}</td>'
                  f'<td class="ticker-cell"><a href="{safe_url(row.get("url"))}">{h(row.get("ticker"))}</a>{new}</td>'
                  f'<td class="name-cell">{h(row.get("name"))}</td><td><span class="asset">{h(row.get("asset_type", "주식"))}</span></td>'
                  f'<td class="number">{aum(row.get("mcap"))}</td>'
                  f'<td class="number">{pct(row.get("gap", 0))}</td>'
                  f'<td>{h(row.get("industry") or "-")}</td>'
                  f'<td class="number">{pct(row.get("change", 0))}</td>'
                  f'<td class="number">{price_s}</td>'
                  f'<td class="number">{h(row.get("streak", 1))}일째</td><td>{h(badges)}</td></tr>')
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
