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
.shell{max-width:680px;margin:0 auto;padding:18px 12px}.layout{width:100%;table-layout:fixed}
.hero{background:#11243c;color:#fff;border-radius:18px;padding:24px}
.eyebrow{font-size:10px;font-weight:bold;letter-spacing:2px;color:#8fb6c8;margin:0 0 8px}
.hero h1{font-size:28px;line-height:1.25;letter-spacing:-1px;margin:0 0 8px}
.date{font-size:13px;color:#c5d5e4}.hero .foot{font-size:11px;color:#9eb5cc;border-top:1px solid #30465f;padding-top:12px;margin-top:16px}
.summary{margin-top:12px;background:#fff;border:1px solid #dfe7ef;border-radius:14px;padding:16px}
.summary td{width:50%;padding:0 8px}.count{font-size:27px;font-weight:bold;letter-spacing:-1px}
.market{font-weight:bold;font-size:13px;margin-bottom:3px}.muted{font-size:11px;color:#667a90}
.section{margin-top:24px}.section h2{margin:0;font-size:21px;line-height:1.3;letter-spacing:-.6px}
.intro{font-size:12px;color:#667a90;margin:6px 0 14px}
.etf-card{background:#fff;border:1px solid #dce5ee;border-radius:14px;margin:0 0 12px;padding:16px;word-wrap:break-word;word-break:break-word}
.etf-feature{width:106px;text-align:right}
.rank{display:inline-block;background:#163b68;color:#fff;border-radius:5px;padding:1px 6px;font-size:11px;font-weight:bold;margin-right:5px}
.ticker{font-size:13px;font-weight:bold;letter-spacing:.4px}.etf-name{font-size:17px;font-weight:bold;line-height:1.4;margin:8px 10px 12px 0}
.metric-label{display:block;color:#60758c;font-size:11px;font-weight:normal;line-height:1.5}
.metric strong{display:block;font-size:18px;line-height:1.4;letter-spacing:-.4px;word-break:break-word}
.featured strong{font-size:25px}.featured .metric-label{font-size:11px}
.returns td{width:33.33%;padding:10px 3px;text-align:center;background:#f3f6fa;border:2px solid #fff}
.cumulative{background:#edf7f4;padding:10px 12px;border-radius:7px;margin-top:6px}
.cumulative .metric-label{display:inline-block;font-size:11px;color:#42675d}
.cumulative strong{display:inline-block;margin-left:8px;font-size:18px}
.details{font-size:11px;color:#64778b;border-top:1px solid #ecf0f4;padding-top:10px;margin-top:12px;line-height:1.7}
.details b{color:#40566e;font-weight:normal}.up{color:#c04840}.down{color:#2862a6}.flat{color:#52677d}
.new-summary{background:#e8f0f8;border-radius:12px;padding:16px;margin-top:18px}
.new-summary h3{font-size:15px;margin:0 0 8px}.new-summary td{width:50%;font-size:13px}
.new{background:#e6f3ed;color:#237353;border-radius:4px;padding:1px 5px;font-size:10px;font-weight:bold}
.stocks{background:#fff;border:1px solid #dce5ee;border-radius:12px;padding:4px 12px}
.stocks td{padding:11px 0;border-bottom:1px solid #eaf0f5;word-break:break-word;word-wrap:break-word}
.stocks tr:last-child td{border-bottom:0}.stock-name{padding-right:12px!important}
.stock-name a{display:block;font-size:13px;font-weight:bold;line-height:1.45}
.stock-name small{display:block;color:#667a90;font-size:11px;line-height:1.6;margin-top:4px}
.stock-values{width:112px;text-align:right}.stock-values b{font-size:13px;display:block}.stock-values small{display:block;font-size:11px}
.notice{background:#fff4dc;color:#796438;border-radius:8px;padding:10px 12px;font-size:12px;margin:12px 0}
.report-note{padding:12px;background:#e8f0f8;border-radius:8px;color:#405d7a;font-size:12px}
.notes{font-size:10px;line-height:1.7;color:#75869a;margin:14px 0}.footer{text-align:center;color:#8a9aab;font-size:10px;padding:24px 0 12px}
@media screen and (max-width:420px){.shell{padding:10px 8px}.hero{padding:20px 16px}.hero h1{font-size:25px}.summary{padding:13px 8px}.summary td{padding:0 6px}.count{font-size:24px}.etf-card{padding:12px}.etf-name{font-size:15px}.etf-feature{width:96px}.featured strong{font-size:22px}.returns .metric strong{font-size:16px}.stock-values{width:100px}}
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

def metric(period, label, value, extra=""):
    return (f'<div class="metric {extra}" data-period="{period}">'
            f'<span class="metric-label">{label}</span><strong>{pct(value)}</strong></div>')

def etf_section_html(etf_info):
    rows = etf_info.get("rows", [])
    head = ('<div class="section" id="etf"><p class="eyebrow">ETF PERFORMANCE</p>'
            '<h2>ETF 수익률 랭킹</h2>'
            f'<p class="intro">1년 연평균수익률 내림차순 · 상위 {len(rows)}개'
            f' · 산출 가능 {etf_info.get("with_ret", 0)} / 후보 {etf_info.get("pool", 0)}개</p>')
    if not rows:
        return head + '<div class="etf-card muted">해당 ETF 없음</div></div>'
    cards = []
    for i, s in enumerate(rows, 1):
        country = "US" if s.get("market") == "US" else "KR"
        ticker = h(s.get("ticker"))
        cards.append(
            f'<div class="etf-card" data-ticker="{ticker}">'
            '<table role="presentation" class="layout etf-head"><tr><td>'
            f'{flag_html(country)}<span class="rank">{i:02d}</span>'
            f'<a class="ticker" href="{safe_url(s.get("url"))}">{ticker}</a>'
            f'<div class="etf-name">{h(s.get("name"))}</div></td><td class="etf-feature">'
            f'{metric("1y", "최근 1년<br>연평균수익률", s.get("cagr1y"), "featured")}'
            '</td></tr></table><table role="presentation" class="layout returns"><tr>'
            f'<td>{metric("3y", "최근 3년<br>연평균수익률", s.get("cagr3y"))}</td>'
            f'<td>{metric("5y", "최근 5년<br>연평균수익률", s.get("cagr5y"))}</td>'
            f'<td>{metric("10y", "최근 10년<br>연평균수익률", s.get("cagr10y"))}</td>'
            '</tr></table>'
            f'{metric("cumulative", "설립 이래 누적수익률", s.get("cumulative_return"), "cumulative")}'
            '<div class="details">'
            f'<b>추종지수</b> {h(s.get("etf_index"))}<br>'
            f'<b>ETF 성격</b> {h(s.get("etf_kind"))}<br>'
            f'<b>운용사</b> {h(s.get("issuer"))} · <b>AUM</b> {aum(s.get("aum") or s.get("mcap"))}<br>'
            f'<b>설립일</b> {h(s.get("inception") or s.get("first_date"))}'
            '</div></div>')
    notes = ('<p class="notes">ATH -10% 이내 비채권 ETF 기준. 1년 이력이 없는 ETF는 순위에서 제외합니다.<br>'
             '연평균수익률은 복리(CAGR) 기준이며, 해당 기간의 가격 이력이 부족하면 -로 표시합니다.<br>'
             '설립 이래 누적수익률은 수집 가능한 최초 거래일 종가 대비 최신 종가의 전체 상승률이며, 연환산하지 않음.<br>'
             '한국 ETF는 분배금 미반영 가격수익률, 미국 ETF는 배당 재투자 반영 수정주가 기준입니다.<br>'
             '설립일은 운용사 공시값을 우선하고 없으면 최초 거래일, 운용사는 미확인 시 브랜드로 추정합니다.</p>')
    return head + "".join(cards) + notes + "</div>"

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
            f'<div class="market">{flag_html("KR")}한국</div><div class="count">{len(kr)}<span style="font-size:12px"> 종목</span></div>'
            f'<div class="muted">KOSPI {value("kospi")} {pct(indices.get("kospi_chg"))}<br>{h(info.get("kr_last_str"))}</div>'
            '</td><td>'
            f'<div class="market">{flag_html("US")}미국</div><div class="count">{len(us)}<span style="font-size:12px"> 종목</span></div>'
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
    prefix = header + _summary(us, kr, info, indices) + etf_section_html(etf_info) + new_summary(new_us, new_kr)
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
