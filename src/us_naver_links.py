"""Resolve US symbols through Naver's own security search results.

NASDAQ, NYSE and US ETFs use different Reuters codes and detail routes.
Using the URL returned by Naver avoids guessing suffixes or treating an ETF as a stock.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from functools import lru_cache
import logging
import math
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

log = logging.getLogger(__name__)
AUTOCOMPLETE_URL = "https://ac.stock.naver.com/ac"
NAVER_ORIGIN = "https://m.stock.naver.com"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}


def normalize_symbol(value):
    # Yahoo uses BRK-B, whereas Naver's class-share codes use spaces/dots.
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def matching_url(payload, ticker):
    """Return an exact US-symbol match, never a similarly named security."""
    if not isinstance(payload, dict):
        return None
    wanted = normalize_symbol(ticker)
    matches = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("nationCode") != "USA":
            continue
        if normalize_symbol(item.get("code")) != wanted:
            continue
        raw_url = item.get("url")
        if not isinstance(raw_url, str):
            continue
        url = urlsplit(urljoin(NAVER_ORIGIN, raw_url))
        if (url.scheme != "https" or url.netloc != "m.stock.naver.com"
                or url.query or url.fragment
                or not re.fullmatch(r"/worldstock/(?:stock|etf)/[A-Za-z0-9. _-]+(?:/total)?", url.path)):
            continue
        matches.add(urlunsplit(url))
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous Naver symbol: {ticker}")
    return next(iter(matches), None)


def query_variants(ticker):
    ticker = str(ticker).strip().upper()
    candidates = [ticker]
    if "-" in ticker:
        candidates.extend((ticker.replace("-", "."), ticker.replace("-", " "),
                           ticker.split("-", 1)[0], normalize_symbol(ticker)))
    return list(dict.fromkeys(candidates))


def _request_json(url, params=None, *, expected_type=dict):
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=12)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, expected_type):
                raise ValueError("Unexpected Naver JSON response")
            return payload
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(0.3 * (attempt + 1))


def _search(query):
    payload = _request_json(AUTOCOMPLETE_URL,
                            {"q": query, "target": "stock,index,market"})
    if not isinstance(payload.get("items"), list):
        raise ValueError("Unexpected Naver search response")
    return payload


def validate_basic(payload, ticker, url):
    """Bind the chosen link to Naver's actual security identity and detail route."""
    path = urlsplit(url).path
    route, reuters_code = path.split("/")[2:4]
    exchange = payload.get("stockExchangeType") or {}
    nation = payload.get("nationType") or exchange.get("nationCode")
    official = payload.get("stockEndUrl") or payload.get("endUrl") or ""
    normalized_url = url.removesuffix("/total").rstrip("/")
    if (normalize_symbol(payload.get("symbolCode")) != normalize_symbol(ticker)
            or payload.get("reutersCode") != reuters_code
            or payload.get("stockEndType") != route
            or nation != "USA"
            or official.removesuffix("/total").rstrip("/") != normalized_url):
        raise RuntimeError(f"Naver detail identity mismatch: {ticker} -> {url}")
    return url


def _verify_url(ticker, url):
    reuters_code = urlsplit(url).path.split("/")[3]
    payload = _request_json(f"https://api.stock.naver.com/stock/{reuters_code}/basic")
    return validate_basic(payload, ticker, url)


def _quote_date(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:T|$)", value):
        return None
    try:
        return (datetime.fromisoformat(value).date() if len(value) > 10
                else date.fromisoformat(value)).isoformat()
    except (ValueError, OverflowError):
        return None


def _positive_price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value.replace(",", "") if isinstance(value, str) else value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _chart_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def verified_close(ticker, url, day=None):
    """Read Naver's same-day closing quote after verifying the security.

    Historical quotes can be revised after corporate actions. Retain the
    provider's value without assuming a split or dividend adjustment basis.
    """
    if not isinstance(url, str):
        raise RuntimeError(f"Naver detail identity mismatch: {ticker} -> {url}")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "m.stock.naver.com"
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/worldstock/(?:stock|etf)/[A-Za-z0-9. _-]+(?:/total)?", parsed.path)):
        raise RuntimeError(f"Naver detail identity mismatch: {ticker} -> {url}")
    requested = None
    if day is not None:
        requested = day.isoformat() if isinstance(day, date) else str(day)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested):
            raise ValueError("Naver closing quote requires an ISO market date")
        requested = date.fromisoformat(requested).isoformat()
    reuters_code = parsed.path.split("/")[3]
    basic_url = f"https://api.stock.naver.com/stock/{reuters_code}/basic"
    basic = _request_json(basic_url)
    validate_basic(basic, ticker, url)
    observed = _quote_date(basic.get("localTradedAt"))
    price = _positive_price(basic.get("closePriceRaw")) or _positive_price(basic.get("closePrice"))
    if observed and price is not None and (requested is None or requested == observed):
        return {"price": price, "date": observed, "source_url": basic_url}
    if requested is None:
        return None
    compact_date = requested.replace("-", "")
    chart_url = f"https://api.stock.naver.com/chart/foreign/item/{reuters_code}/day"
    params = {"startDateTime": compact_date + "0000", "endDateTime": compact_date + "2359"}
    items = _request_json(chart_url, params, expected_type=list)
    if not isinstance(items, list):
        return None
    quotes = set()
    for item in items:
        if not isinstance(item, dict) or _chart_date(item.get("localDate")) != requested:
            continue
        close = _positive_price(item.get("closePrice"))
        if close is not None:
            quotes.add(close)
    if len(quotes) > 1:
        raise RuntimeError(f"Naver daily closing quotes conflict: {ticker} {requested}")
    if not quotes:
        return None
    source_url = chart_url + "?startDateTime=" + params["startDateTime"] + "&endDateTime=" + params["endDateTime"]
    return {"price": quotes.pop(), "date": requested, "source_url": source_url}


@lru_cache(maxsize=4096)
def resolve_us_url(ticker):
    """Use Naver's returned URL, including its ETF route and actual Reuters code."""
    for query in query_variants(ticker):
        url = matching_url(_search(query), ticker)
        if url:
            return _verify_url(ticker, url)
    raise RuntimeError(f"Naver has no exact US security match: {ticker}")


def resolve_us_links(rows):
    """Resolve the full candidate list before changing any links or sending mail."""
    if not rows:
        return
    resolved, failures = {}, {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(resolve_us_url, row["ticker"]): row["ticker"]
                   for row in rows}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                resolved[ticker] = future.result()
            except Exception as exc:
                failures[ticker] = str(exc)
    if failures:
        details = "; ".join(f"{ticker}: {message}" for ticker, message in sorted(failures.items()))
        raise RuntimeError(f"Naver links unresolved ({len(failures)}): {details}")
    for row in rows:
        row["url"] = resolved[row["ticker"]]
    log.info("미국 네이버증권 링크 확인: %d/%d (공식 검색·종목 기본 정보의 티커·미국·상세 URL 일치)",
             len(resolved), len(rows))
