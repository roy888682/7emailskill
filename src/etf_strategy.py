"""Sourced ETF management styles; an index label alone is not passive evidence."""
import re
from urllib.parse import quote, urlsplit

STYLE_FIELDS = ("management_style", "management_style_source", "management_style_url",
                "management_style_verified", "management_style_evidence")

# Each entry is backed by an issuer document checked for this report change.
# Leveraged exposure does not make a fund active: its stated strategy controls.
OFFICIAL_STYLES = {
    "TQQQ": ("Passive", "ProShares 상품 공시", "https://www.proshares.com/our-etfs/leveraged-and-inverse/tqqq",
             "나스닥100 지수 일일 수익률의 3배 추종 목적"),
    "UPRO": ("Passive", "ProShares 상품 공시", "https://www.proshares.com/our-etfs/leveraged-and-inverse/upro",
             "S&P500 지수 일일 수익률의 3배 추종 목적"),
    "SPXL": ("Passive", "Direxion 상품 공시", "https://www.direxion.com/product/daily-sp-500-bull-bear-3x-etfs",
             "운용사 Passive Investment 명시·S&P500 지수 일일 3배 추종"),
    "MAGS": ("Active", "Roundhill 상품 공시", "https://www.roundhillinvestments.com/etf/mags/",
             "운용사 FAQ에 액티브 운용 명시"),
    "JEPI": ("Active", "J.P. Morgan 액티브 ETF 공시", "https://am.jpmorgan.com/us/en/asset-management/per/investment-strategies/etf-investing/capabilities/active-etfs/",
             "운용사 액티브 ETF 상품 목록"),
    "JEPQ": ("Active", "J.P. Morgan 액티브 ETF 공시", "https://am.jpmorgan.com/us/en/asset-management/per/investment-strategies/etf-investing/capabilities/active-etfs/",
             "운용사 액티브 ETF 상품 목록"),
    "AVUV": ("Active", "Avantis 상품 공시", "https://www.avantisinvestors.com/avantis-investments/avantis-us-small-cap-value-etf/AVUV/",
             "운용사 액티브 운용·특정 지수 복제 목적 아님 명시"),
    "DFAC": ("Active", "Dimensional ETF Quick Guide", "https://my.dimensional.com/chmedia/282748/source/dimensional-etf-quick-guide.pdf",
             "운용사 액티브 투명 ETF 상품 목록"),
}

OFFICIAL_KR_STYLES = {
    "449180": ("Passive", "삼성자산운용 KODEX 상품 공시", "https://www.samsungfund.com/etf/product/view.do?id=2ETFI3",
               "운용사 공시에 기초지수 수익률과 유사하도록 운용하는 목적 명시"),
}


def _country(item):
    value = item.get("country") or item.get("market")
    return "US" if value == "US" else "KR" if value in ("KR", "KOSPI", "KOSDAQ") else None


def _official(item):
    country = _country(item)
    registry = OFFICIAL_STYLES if country == "US" else OFFICIAL_KR_STYLES if country == "KR" else {}
    return registry.get(str(item.get("ticker") or "").upper())


def _fields(style, source, url, evidence, verified=False):
    return dict(zip(STYLE_FIELDS, (style, source, url, verified, evidence)))


def unknown_management_style():
    return _fields("미확인", "운용방식 근거 미확인", None, None)


def management_style_error(item):
    """Validate recorded provenance without upgrading a vendor claim to official."""
    if not all(key in item for key in STYLE_FIELDS):
        return "ETF management-style evidence is missing or incomplete"
    style, source, url, verified, evidence = (item[key] for key in STYLE_FIELDS)
    if style not in ("Active", "Passive", "미확인") or type(verified) is not bool:
        return "ETF management style or verification status is invalid"
    if not isinstance(source, str) or not source.strip():
        return "ETF management style has no source label"
    if style == "미확인":
        if verified or url is not None or evidence is not None:
            return "Unknown ETF management style must not claim verified evidence"
        return None
    try:
        valid_url = isinstance(url, str) and urlsplit(url).scheme == "https" and bool(urlsplit(url).netloc)
    except ValueError:
        valid_url = False
    if not isinstance(evidence, str) or not evidence.strip() or not valid_url:
        return "Known ETF management style requires its source URL and evidence"
    if verified:
        official = _official(item)
        if (official is None
                or (style, source, url, evidence) != official):
            return "Verified ETF management style contradicts its checked issuer document"
    return None


def management_style_metadata(item, vendor_info=None):
    """Prefer recorded evidence, then checked issuers, then explicit provider facts."""
    # Prepared audit records and synthetic fixtures retain their exact provenance.
    # A malformed existing claim is rejected rather than quietly replaced.
    if any(key in item for key in STYLE_FIELDS):
        error = management_style_error(item)
        if error:
            raise ValueError(error)
        return {key: item[key] for key in STYLE_FIELDS}
    ticker = str(item.get("ticker") or "").upper()
    country = _country(item)
    official = _official(item)
    if official:
        return _fields(official[0], official[1], official[2], official[3], True)
    vendor_info = vendor_info if isinstance(vendor_info, dict) else {}
    url = ("https://finance.yahoo.com/quote/" + quote(ticker) + "/profile/" if country == "US" else
           "https://stock.naver.com/domestic/stock/" + quote(ticker) + "/total")
    label = "Yahoo 펀드 운용방식 필드" if country == "US" else "네이버 ETF 운용방식 필드"
    for key in ("managementStyle", "managementType", "investmentManagementType", "etfManagementType"):
        value = str(vendor_info.get(key) or "").strip().casefold()
        if value in ("active", "actively managed", "액티브"):
            return _fields("Active", label, url, "제공업체가 액티브 운용방식을 명시")
        if value in ("passive", "passively managed", "index tracking", "패시브", "인덱스"):
            return _fields("Passive", label, url, "제공업체가 패시브 운용방식을 명시")
    if type(vendor_info.get("isActivelyManaged")) is bool:
        active = vendor_info["isActivelyManaged"]
        return _fields("Active" if active else "Passive", label, url,
                       "제공업체 isActivelyManaged 필드가 운용방식을 명시")
    summary = str(vendor_info.get("longBusinessSummary") or "")
    # Benchmark comparisons are not tracking objectives. Active always takes
    # precedence when an active fund also mentions its comparison index.
    if (re.search(r"\bactively[ -]managed\b", summary, re.I)
            and not re.search(r"\bnot\b[^.;]{0,20}\bactively[ -]managed\b", summary, re.I)):
        return _fields("Active", "Yahoo 펀드 운용 설명", url, "펀드 설명에 액티브 운용 명시")
    explicitly_passive = (re.search(r"\b(?:passively[ -]managed|passive (?:or mathematical |investment )?approach|indexing investment approach)\b", summary, re.I)
                          and not re.search(r"\bnot\b[^.;]{0,20}\b(?:passively[ -]managed|passive|indexing)", summary, re.I))
    not_active = re.search(r"\bnot\b[^.;]{0,20}\bactively[ -]managed\b", summary, re.I)
    tracking_objective = (not re.search(r"\b(?:not|does not|do not|rather than)\b[^.;]{0,50}\b(?:track|replicat|correspond)", summary, re.I)
                          and (re.search(r"\b(?:track\w*|replicat\w*)[^.;]{0,180}\bindex\b", summary, re.I)
                               or re.search(r"\b(?:seeks?|designed|aims?)[^.;]{0,100}\b(?:correspond\w*|match\w*|correlat\w*)[^.;]{0,180}\bindex\b", summary, re.I)))
    if explicitly_passive or not_active or tracking_objective:
        return _fields("Passive", "Yahoo 펀드 운용 설명", url, "펀드 설명에 지수 수익 추종 목적 명시")
    korean_classification = str(vendor_info.get("etfType") or item.get("investment_area") or "")
    if country != "US" and ("액티브" in korean_classification or "액티브" in str(item.get("name") or "")):
        return _fields("Active", "네이버 ETF 분류·종목명", url, "제공 분류 또는 종목명에 액티브 명시")
    if country != "US" and "패시브" in korean_classification:
        return _fields("Passive", "네이버 ETF 분류", url, "제공 분류에 패시브 명시")
    return unknown_management_style()
