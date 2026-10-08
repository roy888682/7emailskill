#!/usr/bin/env python3
import os, smtplib, logging, time, io, re, json, bisect, math
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path

if __package__:
    from . import email_layout, email_flags
else:
    import email_layout, email_flags
from datetime import datetime, timedelta, date, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 한국 업종 정적 매핑표 ────────────────────────────────────────────
# 네이버의 실제 공개 API에는 종목→업종명을 직접 주는 창구가 없음이 확인됨
# (2026-09-22 확정: 5가지 API 방식 전부 실패 - 마지막 시도는 다른 개발자의
#  자체 백엔드 주소를 잘못 참조한 것으로 404 확정). 그래서 ATH 후보에 자주
# 등장하는 시가총액 상위권 종목 위주로 직접 정리한 정적 표를 사용함.
# 표에 없는 종목은 -로 표시됨. 특정 종목이 계속 -로 나오면 아래에
# 종목코드: 업종명 한 줄만 추가하면 됨.
KR_INDUSTRY_STATIC = {
    "005930":"반도체", "000660":"반도체", "042700":"반도체장비",
    "403870":"반도체장비", "112040":"반도체장비", "039030":"반도체장비",
    "373220":"이차전지", "006400":"전자부품", "247540":"이차전지소재",
    "086520":"이차전지소재", "066970":"반도체장비",
    "207940":"바이오", "068270":"바이오", "196170":"바이오",
    "128940":"제약", "185750":"제약", "145020":"제약", "096530":"제약",
    "091990":"바이오", "298380":"바이오", "141080":"바이오",
    "214150":"의료기기",
    "005380":"자동차", "000270":"자동차", "012330":"자동차부품",
    "204320":"자동차부품", "018880":"자동차부품",
    "035420":"인터넷", "035720":"인터넷", "036570":"게임",
    "251270":"게임", "293490":"게임", "263750":"게임",
    "105560":"금융", "055550":"금융", "086790":"금융", "316140":"금융",
    "032830":"보험", "000810":"보험",
    "003550":"지주회사", "034730":"지주회사", "028050":"건설",
    "005490":"철강", "051910":"화학", "011170":"화학", "004020":"철강",
    "010130":"비철금속", "003670":"이차전지소재",
    "009540":"조선", "042660":"조선", "010140":"조선",
    "066570":"전자", "009150":"전자부품",
    "096770":"정유화학", "010950":"정유", "015760":"전력",
    "267250":"조선기자재",
    "017670":"통신", "030200":"통신", "032640":"통신",
    "352820":"엔터", "041510":"엔터", "122870":"엔터", "035900":"엔터",
    "090430":"화장품", "051900":"생활용품", "097950":"식품", "271560":"식품",
    "011200":"해운", "047050":"무역", "023530":"유통",
    "018260":"IT서비스", "058470":"반도체장비",
}

INDUSTRY_KR = {
    # GICS 11개 섹터
    "Technology":"기술","Healthcare":"헬스케어","Financial Services":"금융",
    "Consumer Cyclical":"경기소비재","Consumer Defensive":"필수소비재",
    "Industrials":"산업재","Energy":"에너지","Utilities":"유틸리티",
    "Real Estate":"부동산","Basic Materials":"소재","Communication Services":"커뮤니케이션서비스",
    # 세부 업종 (자주 등장하는 항목)
    "Semiconductors":"반도체","Semiconductor Equipment & Materials":"반도체 장비·소재",
    "Software—Infrastructure":"소프트웨어(인프라)","Software—Application":"소프트웨어(응용)",
    "Internet Content & Information":"인터넷 콘텐츠·정보","Internet Retail":"인터넷 소매",
    "Banks—Regional":"지역은행","Banks—Diversified":"종합은행",
    "Insurance—Diversified":"복합보험","Insurance—Property & Casualty":"손해보험",
    "Insurance—Life":"생명보험","Insurance—Specialty":"전문보험","Insurance Brokers":"보험중개",
    "Asset Management":"자산운용","Capital Markets":"자본시장",
    "Drug Manufacturers—General":"제약","Drug Manufacturers—Specialty & Generic":"특수·제네릭 제약",
    "Biotechnology":"바이오기술","Medical Devices":"의료기기","Medical Instruments & Supplies":"의료기기·용품",
    "Healthcare Plans":"건강보험","Diagnostics & Research":"진단·연구","Medical Care Facilities":"의료시설",
    "Specialty Retail":"전문소매","Discount Stores":"할인점","Restaurants":"외식업",
    "Auto Manufacturers":"자동차 제조","Auto Parts":"자동차 부품",
    "Aerospace & Defense":"항공우주·방위","Airlines":"항공",
    "Oil & Gas Integrated":"석유·가스(종합)","Oil & Gas E&P":"석유·가스 탐사생산",
    "Oil & Gas Midstream":"석유·가스 미드스트림","Oil & Gas Refining & Marketing":"정유·마케팅",
    "Oil & Gas Equipment & Services":"석유·가스 장비·서비스",
    "Utilities—Regulated Electric":"전력유틸리티","Utilities—Diversified":"종합유틸리티",
    "REIT—Diversified":"복합리츠","REIT—Retail":"리테일리츠","REIT—Residential":"주거리츠",
    "REIT—Office":"오피스리츠","REIT—Industrial":"산업용리츠","REIT—Healthcare Facilities":"헬스케어리츠",
    "Telecom Services":"통신서비스","Entertainment":"엔터테인먼트",
    "Electronic Gaming & Multimedia":"게임·멀티미디어","Consumer Electronics":"가전",
    "Specialty Chemicals":"특수화학","Chemicals":"화학","Building Materials":"건축자재",
    "Packaging & Containers":"포장재","Beverages—Non-Alcoholic":"음료(무알코올)",
    "Beverages—Wineries & Distilleries":"주류","Beverages—Brewers":"맥주",
    "Packaged Foods":"가공식품","Farm Products":"농산물",
    "Household & Personal Products":"생활용품","Apparel Manufacturing":"의류제조",
    "Apparel Retail":"의류소매","Footwear & Accessories":"신발·액세서리",
    "Credit Services":"신용서비스","Information Technology Services":"IT서비스",
    "Communication Equipment":"통신장비","Electronic Components":"전자부품",
    "Computer Hardware":"컴퓨터하드웨어","Scientific & Technical Instruments":"과학기술기기",
    "Industrial Distribution":"산업유통","Specialty Industrial Machinery":"특수산업기계",
    "Farm & Heavy Construction Machinery":"농기계·중장비","Metal Fabrication":"금속가공",
    "Railroads":"철도","Trucking":"화물운송","Integrated Freight & Logistics":"물류",
    "Marine Shipping":"해운","Waste Management":"폐기물관리",
    "Engineering & Construction":"엔지니어링·건설","Conglomerates":"복합기업",
    "Staffing & Employment Services":"인력파견","Security & Protection Services":"보안서비스",
    "Specialty Business Services":"전문비즈니스서비스","Consulting Services":"컨설팅서비스",
    "Gold":"금","Silver":"은","Copper":"구리","Steel":"철강","Aluminum":"알루미늄",
    "Lodging":"숙박","Resorts & Casinos":"리조트·카지노","Travel Services":"여행서비스",
    "Personal Services":"개인서비스","Education & Training Services":"교육·훈련서비스",
    "Tobacco":"담배","Confectioners":"제과","Grocery Stores":"식료품점",
    "Home Improvement Retail":"홈인테리어 소매","Department Stores":"백화점",
}

def get_us_industry(ticker: str):
    """yfinance sector/industry 정보를 한글로 매핑해서 반환 (사전에 없으면 영문 그대로)"""
    try:
        info = yf.Ticker(ticker).info
        ind = info.get("industry") or info.get("sector")
        if not ind: return None
        return INDUSTRY_KR.get(ind, ind)
    except Exception:
        return None
import pytz, yfinance as yf, requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
UA  = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
       "Accept-Language":"ko-KR,ko;q=0.9"}

SNAPSHOT_FILE = "data/daily_snapshots.json"

def load_snapshots() -> dict:
    """거래일별 스냅샷 로드. 구조: {"US":{"2026-06-26":["AAPL",...]}, "KR":{...}}"""
    try:
        if os.path.exists(SNAPSHOT_FILE):
            with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"스냅샷 로드 실패: {e}")
    return {"US": {}, "KR": {}}

def save_snapshots(snapshots: dict) -> None:
    try:
        os.makedirs("data", exist_ok=True)
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)
        log.info("스냅샷 저장 완료")
    except Exception as e:
        log.error(f"스냅샷 저장 실패: {e}")

def compute_new_tickers(stocks: list, snapshots: dict, market_key: str, date_key: str):
    """
    같은 거래일(date_key)을 몇 번 재실행해도 항상 동일한 결과가 나오도록,
    '바로 직전 거래일' 스냅샷과만 비교한다 (누적 이력 전체와 비교하지 않음).
    """
    bucket = snapshots.setdefault(market_key, {})

    # date_key보다 엄격히 이전인 날짜들 중 최신 날짜 = 직전 거래일
    prior_dates = sorted(d for d in bucket if d < date_key)
    prev_set = set(bucket[prior_dates[-1]]) if prior_dates else None

    today_set = {s["ticker"] for s in stocks}

    if prev_set is None:
        # 최초 실행 → 오늘을 baseline으로만 저장, 신규 없음 (전부 신규 처리 안 함)
        new_set = set()
    else:
        new_set = today_set - prev_set

    # 오늘 거래일 스냅샷은 항상 "전체 후보 목록"으로 덮어쓴다 (재실행해도 동일 결과 보장)
    bucket[date_key] = sorted(today_set)

    new_stocks = [s for s in stocks if s["ticker"] in new_set]
    return new_stocks

def compute_streak_counts(snapshots: dict, market_key: str) -> dict:
    """
    별도 DB 없이 daily_snapshots.json만 재활용.
    각 티커가 저장된 거래일 스냅샷에 총 며칠 등장했는지 세기만 하면 됨 (오늘 포함).
    """
    counts = {}
    for date_key, tickers in snapshots.get(market_key, {}).items():
        for tk in tickers:
            counts[tk] = counts.get(tk, 0) + 1
    return counts

def new_tickers_html(new_us: list, new_kr: list) -> str:
    return email_layout.new_summary(new_us, new_kr)

DOW30={"AAPL","MSFT","UNH","GS","HD","AMGN","CAT","CRM","CVX","BA",
       "MCD","HON","V","JPM","AXP","MRK","IBM","MMM","NKE","JNJ",
       "TRV","WMT","PG","VZ","DIS","KO","DOW","CSCO","WBA","NVDA"}

# ── 공통 ──────────────────────────────────────────────
def get_usd_krw():
    try:
        h=yf.Ticker("USDKRW=X").history(period="5d",auto_adjust=True)
        r=float(h["Close"].iloc[-1]); log.info(f"USD/KRW:{r:,.1f}"); return r
    except: return 1380.0

def get_market_indices():
    """S&P500, KOSPI 지수 + 전일대비 등락률 조회 (실패시 None)"""
    import math
    result = {"sp500": None, "kospi": None, "sp500_chg": None, "kospi_chg": None}
    try:
        h = yf.Ticker("^GSPC").history(period="5d", auto_adjust=True)["Close"].dropna()
        last = float(h.iloc[-1]); prev = float(h.iloc[-2])
        if not math.isnan(last) and not math.isnan(prev):
            result["sp500"] = last
            result["sp500_chg"] = round((last - prev) / prev * 100, 2)
    except Exception as e:
        log.warning(f"S&P500 조회 실패: {e}")
    try:
        h = yf.Ticker("^KS11").history(period="5d", auto_adjust=True)["Close"].dropna()
        last = float(h.iloc[-1]); prev = float(h.iloc[-2])
        if not math.isnan(last) and not math.isnan(prev):
            result["kospi"] = last
            result["kospi_chg"] = round((last - prev) / prev * 100, 2)
    except Exception as e:
        log.warning(f"KOSPI 조회 실패: {e}")
    log.info(f"S&P500:{result['sp500']}({result['sp500_chg']}%) KOSPI:{result['kospi']}({result['kospi_chg']}%)")
    return result

def date_str(d):
    if d is None: return "확인불가"
    return d.strftime(f"%Y년 %m월 %d일({'월화수목금토일'[d.weekday()]})")

def prev_weekday(d):
    p=d-timedelta(days=1)
    while p.weekday()>=5: p-=timedelta(days=1)
    return p

def get_trading_info():
    today=datetime.now(KST).date(); expected=prev_weekday(today)
    def lt(sym):
        try:
            today_kst=datetime.now(KST).date()
            h=yf.Ticker(sym).history(period="10d",auto_adjust=True)
            if h.empty: return None
            # 오늘 날짜 제외 — yfinance가 오늘 날짜를 포함해서 반환하는 경우 방지
            dates=[d.date() if hasattr(d,"date") else d for d in h.index]
            past=[d for d in dates if d<today_kst]
            return max(past) if past else None
        except: return None
    us_last=lt("SPY"); kr_last=lt("005930.KS")
    us_hol=(us_last!=expected) if us_last else False
    kr_hol=(kr_last!=expected) if kr_last else False
    def hm(exp,act,mkt):
        if not act: return ""
        return f"직전 영업일({date_str(exp)})이 {mkt} 휴장이므로 직직전 영업일 기준: {date_str(act)}"
    log.info(f"오늘:{today} 직전평일:{expected} US:{us_last}(휴:{us_hol}) KR:{kr_last}(휴:{kr_hol})")
    return {"expected":expected,"us_last":us_last,"kr_last":kr_last,
            "us_last_str":date_str(us_last),"kr_last_str":date_str(kr_last),
            "us_holiday":us_hol,"kr_holiday":kr_hol,
            "us_holiday_msg":hm(expected,us_last,"미국") if us_hol else "",
            "kr_holiday_msg":hm(expected,kr_last,"한국") if kr_hol else ""}

# ── 미국: 2단계 yfinance ──────────────────────────────
# ══ ETF 전용 섹션용 헬퍼 ══════════════════════════════════════════════════
# 한국 ETF 상세(ETFBase) 응답 필드명은 공개 문서에 없어서, 후보 키를 여러 개 시도하고
# 첫 응답 구조를 로그([진단ETF])로 남김. 못 찾으면 "-" 또는 대체값(브랜드→운용사,
# 최초 거래일→설립일)으로 채움.

def _calc_perf(dates, closes):
    """(1년·3년·5년·10년 CAGR%, 최초 거래일부터의 누적수익률%, 최초거래일)."""
    if not dates or len(dates) != len(closes) or len(closes) < 2:
        return None, None, None, None, None, None
    last_d, last_p = dates[-1], closes[-1]

    def cagr(years):
        try:
            target = last_d.replace(year=last_d.year - years)
        except ValueError:  # 2월 29일의 과거 기준 연도가 평년이면 2월 28일 사용
            target = last_d.replace(year=last_d.year - years, day=28)
        i = bisect.bisect_right(dates, target) - 1
        if i < 0:
            return None
        start_p = closes[i]  # 기준일이 휴장이면 직전 거래일 종가
        if (not math.isfinite(last_p) or not math.isfinite(start_p)
                or last_p <= 0 or start_p <= 0):
            return None
        return round(((last_p / start_p) ** (1 / years) - 1) * 100, 1)

    first_p = closes[0]
    cumulative = None
    if (math.isfinite(last_p) and math.isfinite(first_p)
            and last_p > 0 and first_p > 0):
        cumulative = round((last_p / first_p - 1) * 100, 1)

    return cagr(1), cagr(3), cagr(5), cagr(10), cumulative, dates[0]

def _flatten(d, prefix="", depth=0):
    flat = {}
    if not isinstance(d, dict):
        return flat
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 2:
            flat.update(_flatten(v, key + ".", depth + 1))
        else:
            flat[key] = v
    return flat

def _find_val(flat, rules):
    """rules: [(must_all, must_any, exclude), ...] 순서대로 첫 매칭 값 반환 (str/int만)."""
    for must_all, must_any, exclude in rules:
        for k, v in flat.items():
            if not isinstance(v, (str, int)) or isinstance(v, bool):
                continue
            if isinstance(v, str) and not v.strip():
                continue
            kl = k.lower()
            if all(m in kl for m in must_all) \
               and (not must_any or any(m in kl for m in must_any)) \
               and not any(e in kl for e in exclude):
                return v.strip() if isinstance(v, str) else v
    return None

def _norm_date(v):
    s = re.sub(r"[^0-9]", "", str(v or ""))
    if len(s) >= 8:
        y, m, d = s[:4], s[4:6], s[6:8]
        if 1980 <= int(y) <= 2100 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{m}-{d}"
    return None

def _extract_rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "list", "etfs", "contents", "data", "content", "stocks", "result"):
            v = data.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = _extract_rows(v)
                if inner:
                    return inner
    return []

def _won_to_jo(v):
    """AUM 숫자를 조원으로. 단위가 문서화돼 있지 않아 크기로 판별:
    1e8 이상이면 원, 미만이면 억원 (ETF 순자산이 1만조 이상일 수는 없으므로 안전)."""
    try:
        x = float(str(v).replace(",", ""))
    except Exception:
        return None
    if x <= 0:
        return None
    return round(x / 1e12, 4) if x >= 1e8 else round(x / 1e4, 4)

# ── 한국 ETF 이름 기반 판별/분류 ────────────────────────────────────────────
KR_ETF_BRANDS = ("KODEX","TIGER","ACE","KBSTAR","SOL","HANARO","ARIRANG","KOSEF",
                 "KINDEX","TIMEFOLIO","WOORI","FOCUS","마이다스","히어로즈","RISE","PLUS",
                 "KIWOOM","1Q","TIME ","WON ","BNK","HK ","TREX","UNICORN","마이티",
                 "파워","에셋플러스","KOACT","TRUSTON")
KR_BOND_ETF_KEYWORDS = ("채권","국채","국고채","회사채","통안채","크레딧","단기자금","종합채권",
                        "CD금리","MMF","머니마켓","KOFR","SOFR","금리","하이일드","미국채")
KR_ETF_ISSUER_BRANDS = (
    ("KODEX","삼성자산운용"),("TIGER","미래에셋자산운용"),("ACE","한국투자신탁운용"),
    ("KBSTAR","KB자산운용"),("RISE","KB자산운용"),("SOL","신한자산운용"),
    ("HANARO","NH-Amundi자산운용"),("ARIRANG","한화자산운용"),("PLUS","한화자산운용"),
    ("KOSEF","키움투자자산운용"),("KIWOOM","키움투자자산운용"),("히어로즈","키움투자자산운용"),
    ("KINDEX","한국투자신탁운용"),("1Q","하나자산운용"),("TIMEFOLIO","타임폴리오자산운용"),
    ("TIME ","타임폴리오자산운용"),("WOORI","우리자산운용"),("WON ","우리자산운용"),
    ("FOCUS","브이아이자산운용"),("마이다스","마이다스에셋자산운용"),("TREX","유리자산운용"),
    ("HK ","흥국자산운용"),("BNK","BNK자산운용"),("UNICORN","현대자산운용"),
    ("마이티","DB자산운용"),("파워","교보악사자산운용"),("에셋플러스","에셋플러스자산운용"),
    ("KOACT","삼성액티브자산운용"),("TRUSTON","트러스톤자산운용"),
)

def kr_is_etf_name(name: str) -> bool:
    return any(name.upper().startswith(b) for b in KR_ETF_BRANDS)

def kr_is_bond_etf(name: str) -> bool:
    return any(kw in name for kw in KR_BOND_ETF_KEYWORDS)

def kr_issuer_from_brand(name: str):
    up = name.upper()
    for b, issuer in KR_ETF_ISSUER_BRANDS:
        if up.startswith(b):
            return issuer
    return None

def classify_kr_etf(name: str) -> str:
    """ETF 이름 키워드로 자산군/테마 분류 (예: '주식 · 미국 반도체', '원자재 · 금')."""
    n = name.upper()
    tag = " (인버스)" if "인버스" in name else (" (레버리지)" if ("레버리지" in name or "2X" in n) else "")
    if re.search(r"골드|금현물|KRX ?금|금선물|(?<![가-힣])금(?![가-힣융])", name):
        return "원자재 · 금" + tag
    if re.search(r"은선물|실버|(?<![가-힣])은(?![가-힣행])\b", name) and "은행" not in name:
        return "원자재 · 은" + tag
    for kw, label in (("구리","구리"),("원유","원유"),("WTI","원유"),("천연가스","천연가스"),
                      ("농산물","농산물"),("콩","농산물"),("원자재","원자재"),("팔라듐","귀금속"),
                      ("탄소배출권","탄소배출권")):
        if kw in name or kw in n:
            return f"원자재 · {label}" + tag
    if re.search(r"비트코인|이더리움|BTC|ETH", n):
        return "가상자산" + tag
    if re.search(r"리츠|부동산", name):
        return "부동산(리츠)" + tag
    if re.search(r"달러선물|엔선물|위안|엔화|달러(?!채)", name):
        return "통화" + tag
    region = None
    for pat, label in ((r"미국|나스닥|S&P|다우|NASDAQ|(?<![A-Z])US(?![A-Z])", "미국"), (r"중국|차이나|항셍|CSI|홍콩", "중국"),
                       (r"인도(?!네시아)", "인도"), (r"일본|닛케이|TOPIX", "일본"), (r"베트남", "베트남"),
                       (r"유럽|독일|영국|프랑스", "유럽"), (r"신흥국|글로벌|선진국|MSCI|해외|아시아", "해외")):
        if re.search(pat, n):
            region = label
            break
    theme = None
    for pat, label in ((r"반도체", "반도체"), (r"2차전지|배터리", "2차전지"),
                       (r"바이오|헬스케어|제약", "바이오/헬스케어"), (r"(?<![A-Z])AI(?![A-Z])|인공지능", "AI"),
                       (r"로봇", "로봇"), (r"방산|우주", "방산/우주"), (r"조선|해운", "조선/해운"),
                       (r"자동차|전기차", "자동차"), (r"은행|증권|보험|금융", "금융"),
                       (r"건설|인프라", "건설/인프라"), (r"원자력|원전|전력|에너지|태양광|수소", "에너지"),
                       (r"게임|미디어|콘텐츠|엔터", "미디어/게임"),
                       (r"소프트웨어|클라우드|인터넷|플랫폼|테크|빅테크", "IT/플랫폼"),
                       (r"배당|커버드콜|프리미엄|인컴", "배당/인컴"),
                       (r"ESG|밸류|퀄리티|모멘텀|저변동|팩터", "스타일/팩터"),
                       (r"코스피|KOSPI|200|코스닥|KRX300|TOP ?10|지수", "시장지수")):
        if re.search(pat, n):
            theme = label
            break
    label = " ".join(x for x in (region, theme or ("시장지수" if region else None)) if x) or "시장지수"
    return "주식 · " + (label or "기타") + tag

# ── 한국 ETF 목록/상세 수집 ────────────────────────────────────────────────
_KR_ETF_DIAG = {"base_logged": False}

def get_kr_etf_universe() -> dict:
    """국내 ETF 목록 (AUM 큰 순). 응답 구조 미문서화 → 후보 키 탐색 + 진단 로그."""
    out = {}
    url = "https://stock.naver.com/api/stockSecurity/etfs/v2/domestic"
    rows = []
    for size in (300, 100):
        try:
            r = requests.get(url, headers=UA,
                             params={"listingType": "aumDesc", "size": size, "index": 0}, timeout=20)
            log.info(f"  [진단ETF] 목록 size={size} status={r.status_code} 응답길이={len(r.text)}")
            if r.status_code != 200:
                log.warning(f"  [진단ETF] 목록 body일부: {r.text[:200]}")
                continue
            data = r.json()
            rows = _extract_rows(data)
            if rows:
                break
            log.info(f"  [진단ETF] 목록 구조 이상, 최상위: {list(data.keys())[:15] if isinstance(data, dict) else type(data)}")
        except Exception as e:
            log.warning(f"  [진단ETF] 목록 예외: {e}")
    if rows and isinstance(rows[0], dict):
        log.info(f"  [진단ETF] 첫 행: {json.dumps(rows[0], ensure_ascii=False)[:700]}")
    for row in rows:
        if not isinstance(row, dict):
            continue
        flat = _flatten(row)
        code = str(_find_val(flat, [(["itemcode"], [], []), (["code"], [], ["index", "theme", "type"])]) or "").strip()
        name = str(_find_val(flat, [(["itemname"], [], []), (["name"], [], ["index", "theme", "issuer"])]) or "").strip()
        if len(code) != 6 or not name:
            continue
        aum_raw = _find_val(flat, [(["aum"], [], ["rate", "change"]), (["marketsum"], [], []),
                                   (["marketcap"], [], []), (["totalnav"], [], []),
                                   (["netasset"], [], ["rate"])])
        out[code] = {"name": name, "mcap": _won_to_jo(aum_raw), "market": "KOSPI", "is_etf": True}
    log.info(f"한국 ETF 유니버스: {len(out)}종목")
    return out

def fetch_kr_etf_base(code: str):
    try:
        r = requests.get(f"https://stock.naver.com/api/domestic/detail/{code}/ETFBase",
                         headers=UA, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict):
            if not _KR_ETF_DIAG["base_logged"]:
                _KR_ETF_DIAG["base_logged"] = True
                log.info(f"  [진단ETF] ETFBase {code} 키: {json.dumps(_flatten(data), ensure_ascii=False)[:900]}")
            return data
    except Exception:
        pass
    return None

def parse_kr_etf_base(data):
    flat = _flatten(data)
    index_nm = _find_val(flat, [(["index"], ["name", "nm"], ["rate", "price", "value", "code", "type"]),
                                (["benchmark"], [], ["rate"]), (["underlying"], [], ["rate", "code"]),
                                (["trackingindex"], [], [])])
    issuer = _find_val(flat, [(["issuer"], [], ["code"]), (["manage"], ["company", "corp", "name", "nm"], []),
                              (["amc"], [], []), (["company"], ["name", "nm"], []), (["운용"], [], [])])
    raw_date = _find_val(flat, [(["list"], ["date", "dt", "day"], ["type"]), (["setup"], [], []),
                                (["inception"], [], []), (["establish"], [], []),
                                (["found"], ["date", "dt"], [])])
    return {"etf_index": index_nm if isinstance(index_nm, str) else None,
            "issuer": issuer if isinstance(issuer, str) else None,
            "inception": _norm_date(raw_date)}

# ── 미국 ETF 분류/보강 ───────────────────────────────────────────────────
US_CATEGORY_KO = {
    "Large Blend":"미국 대형 혼합","Large Growth":"미국 대형 성장","Large Value":"미국 대형 가치",
    "Mid-Cap Blend":"미국 중형","Mid-Cap Growth":"미국 중형 성장","Mid-Cap Value":"미국 중형 가치",
    "Small Blend":"미국 소형","Small Growth":"미국 소형 성장","Small Value":"미국 소형 가치",
    "Technology":"기술","Health":"헬스케어","Financial":"금융","Industrials":"산업재",
    "Utilities":"유틸리티","Communications":"커뮤니케이션","Consumer Cyclical":"경기소비재",
    "Consumer Defensive":"필수소비재","Equity Energy":"에너지","Natural Resources":"천연자원",
    "Equity Precious Metals":"귀금속 광산","Miscellaneous Sector":"기타 섹터",
    "Foreign Large Blend":"선진국 대형","Foreign Large Growth":"선진국 성장","Foreign Large Value":"선진국 가치",
    "Diversified Emerging Mkts":"신흥국","Europe Stock":"유럽","Japan Stock":"일본",
    "China Region":"중국","India Equity":"인도","Pacific/Asia ex-Japan Stk":"아시아(일본 제외)",
    "Infrastructure":"인프라","Trading--Leveraged Equity":"레버리지","Trading--Inverse Equity":"인버스",
    "Global Real Estate":"글로벌 리츠","Real Estate":"리츠","World Large Stock":"글로벌 대형",
    "Allocation--50% to 70% Equity":"자산배분","Digital Assets":"가상자산",
}

def classify_us_etf(name: str, category) -> str:
    n = (name or "").upper()
    cat = (category or "")
    cl = cat.lower()
    miners = ("MINER" in n or "MINING" in n)
    if not miners and (("commodit" in cl) or re.search(r"\bGOLD\b|\bSILVER\b|PLATINUM|PALLADIUM|\bOIL\b|CRUDE|NATURAL GAS|COPPER|URANIUM|AGRICULT|COMMODITY", n)):
        sub = "금" if "GOLD" in n else "은" if "SILVER" in n else "원유" if re.search(r"\bOIL\b|CRUDE", n) else \
              "구리" if "COPPER" in n else "천연가스" if "NATURAL GAS" in n else "원자재"
        return f"원자재 · {sub}"
    if "digital asset" in cl or re.search(r"BITCOIN|ETHER(?!NET)|CRYPTO", n):
        return "가상자산"
    if "real estate" in cl or "REIT" in n:
        return "부동산(리츠)"
    if "currency" in cl:
        return "통화"
    return "주식 · " + (US_CATEGORY_KO.get(cat, cat) if cat else "기타")

def _extract_us_index(summary: str):
    if not summary:
        return None
    m = re.search(r"(?:track|tracks|tracking|replicate|replicates|seeks to track|designed to track|benchmark)"
                  r"[^.]{0,140}?\b(?:the\s+)?([A-Z][A-Za-z0-9&\.\-\u00C0-\u017F ]{2,80}?\bIndex)\b", summary)
    return m.group(1).strip() if m else None

def enrich_us_etf(tk: str, name: str, usd_krw: float) -> dict:
    """yfinance info로 운용사·분류·AUM·설립일·추종지수 보강. None 값은 제외해서 반환."""
    res = {}
    try:
        info = yf.Ticker(tk).info or {}
    except Exception:
        info = {}
    res["issuer"] = info.get("fundFamily")
    res["etf_kind"] = classify_us_etf(name, info.get("category"))
    ta = info.get("totalAssets")
    if isinstance(ta, (int, float)) and ta > 0:
        res["aum"] = round(ta * usd_krw / 1e12, 4)
    inc = info.get("fundInceptionDate")
    if isinstance(inc, (int, float)) and inc > 0:
        try:
            res["inception"] = datetime.fromtimestamp(inc, tz=timezone.utc).date().isoformat()
        except Exception:
            pass
    res["etf_index"] = _extract_us_index(info.get("longBusinessSummary") or "")
    return {k: v for k, v in res.items() if v is not None}


# ── ETF 전용 섹션 HTML ─────────────────────────────────────────────────────
def _etf_pct(v):
    if v is None:
        return "<span style='color:#aaa'>-</span>"
    color = "#c0392b" if v > 0 else "#2980b9" if v < 0 else "#555"
    return f"<span style='color:{color};font-weight:bold'>{v:+.1f}%</span>"

def _etf_aum(v):
    if not v:
        return "-"
    if v < 0.1:
        return f"{v * 1e4:,.0f}억"
    return f"{v:,.2f}조" if v < 10 else f"{v:,.1f}조"

def build_etf_info(us, kr):
    """한국·미국 ETF 중 최근 1년 수익률 내림차순 상위 20개."""
    pool = [s for s in kr + us if s.get("asset_type") == "ETF"]
    ranked = sorted([s for s in pool if s.get("cagr1y") is not None],
                    key=lambda s: s["cagr1y"], reverse=True)
    return {"rows": ranked[:20], "pool": len(pool), "with_ret": len(ranked)}


def etf_section_html(etf_info):
    return email_layout.etf_section_html(etf_info)

def dl(tickers, period, chunk=80, sleep=1.2):
    out={}; n=len(tickers)
    if not n: return out
    for i in range(0,n,chunk):
        grp=tickers[i:i+chunk]; bn=i//chunk+1
        log.info(f"  US[{bn}/{(n+chunk-1)//chunk}] {i+1}~{min(i+chunk,n)}/{n} ({period})")
        try:
            raw=yf.download(grp,period=period,progress=False,auto_adjust=True,group_by="ticker")
            if raw.empty: time.sleep(sleep); continue
            for tk in grp:
                try:
                    s=(raw[tk]["Close"] if len(grp)>1 else raw["Close"]).dropna()
                    if len(s)>=10: out[tk]=s
                except: pass
        except Exception as e: log.error(f"  US[{bn}] {e}")
        time.sleep(sleep)
    log.info(f"  US완료:{len(out)}/{n}"); return out

# 미국 본토 주요 ETF (시가총액·거래량 상위 위주, 채권형 제외). NASDAQ 심볼 파일이 막혀도
# 항상 포함되도록 정적 목록으로 관리함. 빠진 ETF가 있으면 "티커": "이름" 한 줄만 추가하면 됨.
US_MAJOR_ETFS = {
    # 미국 시장 전체/대형주
    "SPY":"SPDR S&P 500 ETF Trust","VOO":"Vanguard S&P 500 ETF","IVV":"iShares Core S&P 500 ETF",
    "VTI":"Vanguard Total Stock Market ETF","QQQ":"Invesco QQQ Trust, Series 1","QQQM":"Invesco NASDAQ 100 ETF",
    "DIA":"SPDR Dow Jones Industrial Average ETF Trust","SPLG":"SPDR Portfolio S&P 500 ETF",
    "RSP":"Invesco S&P 500 Equal Weight ETF","VV":"Vanguard Large-Cap ETF","SCHX":"Schwab U.S. Large-Cap ETF",
    "SCHB":"Schwab U.S. Broad Market ETF","ITOT":"iShares Core S&P Total U.S. Stock Market ETF",
    "IWB":"iShares Russell 1000 ETF","OEF":"iShares S&P 100 ETF","XLG":"Invesco S&P 500 Top 50 ETF",
    "DFAC":"Dimensional U.S. Core Equity 2 ETF","MAGS":"Roundhill Magnificent Seven ETF",
    # 중소형주
    "IWM":"iShares Russell 2000 ETF","IJH":"iShares Core S&P Mid-Cap ETF","IJR":"iShares Core S&P Small-Cap ETF",
    "MDY":"SPDR S&P MidCap 400 ETF Trust","VB":"Vanguard Small-Cap ETF","VO":"Vanguard Mid-Cap ETF",
    "SCHA":"Schwab U.S. Small-Cap ETF","IWR":"iShares Russell Mid-Cap ETF","AVUV":"Avantis U.S. Small Cap Value ETF",
    "VBR":"Vanguard Small-Cap Value ETF","VBK":"Vanguard Small-Cap Growth ETF","VOT":"Vanguard Mid-Cap Growth ETF",
    "IWO":"iShares Russell 2000 Growth ETF","IWN":"iShares Russell 2000 Value ETF","IWP":"iShares Russell Mid-Cap Growth ETF",
    # 성장/가치/팩터
    "VUG":"Vanguard Growth ETF","VTV":"Vanguard Value ETF","IWF":"iShares Russell 1000 Growth ETF",
    "IWD":"iShares Russell 1000 Value ETF","SCHG":"Schwab U.S. Large-Cap Growth ETF","SPYG":"SPDR Portfolio S&P 500 Growth ETF",
    "SPYV":"SPDR Portfolio S&P 500 Value ETF","IVW":"iShares S&P 500 Growth ETF","IVE":"iShares S&P 500 Value ETF",
    "IUSG":"iShares Core S&P U.S. Growth ETF","IUSV":"iShares Core S&P U.S. Value ETF","MTUM":"iShares MSCI USA Momentum Factor ETF",
    "QUAL":"iShares MSCI USA Quality Factor ETF","USMV":"iShares MSCI USA Min Vol Factor ETF","SPMO":"Invesco S&P 500 Momentum ETF",
    "SPHQ":"Invesco S&P 500 Quality ETF","SPLV":"Invesco S&P 500 Low Volatility ETF","COWZ":"Pacer US Cash Cows 100 ETF",
    "MOAT":"VanEck Morningstar Wide Moat ETF",
    # 배당/인컴
    "SCHD":"Schwab U.S. Dividend Equity ETF","VIG":"Vanguard Dividend Appreciation ETF","VYM":"Vanguard High Dividend Yield ETF",
    "DGRO":"iShares Core Dividend Growth ETF","DVY":"iShares Select Dividend ETF","HDV":"iShares Core High Dividend ETF",
    "SDY":"SPDR S&P Dividend ETF","NOBL":"ProShares S&P 500 Dividend Aristocrats ETF","JEPI":"JPMorgan Equity Premium Income ETF",
    "JEPQ":"JPMorgan Nasdaq Equity Premium Income ETF",
    # 섹터
    "XLK":"Technology Select Sector SPDR Fund","XLF":"Financial Select Sector SPDR Fund","XLV":"Health Care Select Sector SPDR Fund",
    "XLE":"Energy Select Sector SPDR Fund","XLY":"Consumer Discretionary Select Sector SPDR Fund",
    "XLP":"Consumer Staples Select Sector SPDR Fund","XLI":"Industrial Select Sector SPDR Fund","XLU":"Utilities Select Sector SPDR Fund",
    "XLB":"Materials Select Sector SPDR Fund","XLRE":"Real Estate Select Sector SPDR Fund","XLC":"Communication Services Select Sector SPDR Fund",
    "VGT":"Vanguard Information Technology ETF","VHT":"Vanguard Health Care ETF","VFH":"Vanguard Financials ETF",
    "VDE":"Vanguard Energy ETF","VIS":"Vanguard Industrials ETF","VPU":"Vanguard Utilities ETF","VOX":"Vanguard Communication Services ETF",
    "FTEC":"Fidelity MSCI Information Technology Index ETF","IYW":"iShares U.S. Technology ETF","IXN":"iShares Global Tech ETF",
    "QTEC":"First Trust NASDAQ-100-Technology Sector Index Fund","FDN":"First Trust Dow Jones Internet Index Fund",
    # 테마/산업
    "SMH":"VanEck Semiconductor ETF","SOXX":"iShares Semiconductor ETF","SOXQ":"Invesco PHLX Semiconductor ETF",
    "XSD":"SPDR S&P Semiconductor ETF","IGV":"iShares Expanded Tech-Software Sector ETF","XBI":"SPDR S&P Biotech ETF",
    "IBB":"iShares Biotechnology ETF","XHB":"SPDR S&P Homebuilders ETF","ITB":"iShares U.S. Home Construction ETF",
    "KRE":"SPDR S&P Regional Banking ETF","KBE":"SPDR S&P Bank ETF","XOP":"SPDR S&P Oil & Gas Exploration & Production ETF",
    "OIH":"VanEck Oil Services ETF","ITA":"iShares U.S. Aerospace & Defense ETF","XAR":"SPDR S&P Aerospace & Defense ETF",
    "ARKK":"ARK Innovation ETF","ARKQ":"ARK Autonomous Technology & Robotics ETF","ARKG":"ARK Genomic Revolution ETF",
    "ARKW":"ARK Next Generation Internet ETF","BOTZ":"Global X Robotics & Artificial Intelligence ETF",
    "ROBO":"ROBO Global Robotics and Automation Index ETF","AIQ":"Global X Artificial Intelligence & Technology ETF",
    "CIBR":"First Trust NASDAQ Cybersecurity ETF","HACK":"Amplify Cybersecurity ETF","SKYY":"First Trust Cloud Computing ETF",
    "CLOU":"Global X Cloud Computing ETF","URA":"Global X Uranium ETF","LIT":"Global X Lithium & Battery Tech ETF",
    "TAN":"Invesco Solar ETF","ICLN":"iShares Global Clean Energy ETF","PAVE":"Global X U.S. Infrastructure Development ETF",
    # 레버리지(서학개미 인기)
    "TQQQ":"ProShares UltraPro QQQ","SOXL":"Direxion Daily Semiconductor Bull 3X Shares","UPRO":"ProShares UltraPro S&P500",
    "SPXL":"Direxion Daily S&P 500 Bull 3X Shares","QLD":"ProShares Ultra QQQ","SSO":"ProShares Ultra S&P500",
    "TECL":"Direxion Daily Technology Bull 3X Shares",
    # 해외/신흥국
    "VEA":"Vanguard FTSE Developed Markets ETF","VWO":"Vanguard FTSE Emerging Markets ETF","IEFA":"iShares Core MSCI EAFE ETF",
    "IEMG":"iShares Core MSCI Emerging Markets ETF","EFA":"iShares MSCI EAFE ETF","EEM":"iShares MSCI Emerging Markets ETF",
    "VXUS":"Vanguard Total International Stock ETF","IXUS":"iShares Core MSCI Total International Stock ETF",
    "ACWI":"iShares MSCI ACWI ETF","VT":"Vanguard Total World Stock ETF","VEU":"Vanguard FTSE All-World ex-US ETF",
    "SCHF":"Schwab International Equity ETF","SCHE":"Schwab Emerging Markets Equity ETF","FXI":"iShares China Large-Cap ETF",
    "MCHI":"iShares MSCI China ETF","KWEB":"KraneShares CSI China Internet ETF","EWJ":"iShares MSCI Japan ETF",
    "EWY":"iShares MSCI South Korea ETF","EWT":"iShares MSCI Taiwan ETF","INDA":"iShares MSCI India ETF",
    "EWZ":"iShares MSCI Brazil ETF","EWG":"iShares MSCI Germany ETF","VGK":"Vanguard FTSE Europe ETF",
    "EZU":"iShares MSCI Eurozone ETF","EWU":"iShares MSCI United Kingdom ETF","EWC":"iShares MSCI Canada ETF",
    "EWA":"iShares MSCI Australia ETF","VNM":"VanEck Vietnam ETF","DXJ":"WisdomTree Japan Hedged Equity Fund",
    # 원자재/귀금속/광산
    "GLD":"SPDR Gold Shares","IAU":"iShares Gold Trust","GLDM":"SPDR Gold MiniShares Trust","SLV":"iShares Silver Trust",
    "PPLT":"abrdn Physical Platinum Shares ETF","PALL":"abrdn Physical Palladium Shares ETF","CPER":"United States Copper Index Fund",
    "USO":"United States Oil Fund LP","UNG":"United States Natural Gas Fund LP","DBC":"Invesco DB Commodity Index Tracking Fund",
    "GSG":"iShares S&P GSCI Commodity-Indexed Trust","DBA":"Invesco DB Agriculture Fund","COPX":"Global X Copper Miners ETF",
    "GDX":"VanEck Gold Miners ETF","GDXJ":"VanEck Junior Gold Miners ETF","SIL":"Global X Silver Miners ETF",
    "URNM":"Sprott Uranium Miners ETF","REMX":"VanEck Rare Earth and Strategic Metals ETF","XME":"SPDR S&P Metals & Mining ETF",
    # 리츠/가상자산/통화
    "VNQ":"Vanguard Real Estate ETF","IYR":"iShares U.S. Real Estate ETF","SCHH":"Schwab U.S. REIT ETF","REET":"iShares Global REIT ETF",
    "IBIT":"iShares Bitcoin Trust ETF","FBTC":"Fidelity Wise Origin Bitcoin Fund","GBTC":"Grayscale Bitcoin Trust ETF",
    "ETHA":"iShares Ethereum Trust ETF","BITO":"ProShares Bitcoin ETF","UUP":"Invesco DB US Dollar Index Bullish Fund",
}

def _load_nasdaq_symbol_file(fname, ec, tc, exch_name, tickers, exchange_map, security_names, etf_flags):
    """NASDAQ 심볼 파일 로드. www 호스트 → ftp 호스트 순으로 시도, 호스트당 10초 타임아웃.
    (2026-09 중순부터 ftp 호스트가 GitHub Actions에서 매번 타임아웃 → 로그로 확인됨)
    ETF는 US_MAJOR_ETFS 소속만 통과시킴 (전체 ETF는 수천 개라 잡음·지연이 큼)."""
    for base in ("https://www.nasdaqtrader.com/dynamic/SymbolDirectory/",
                 "https://ftp.nasdaqtrader.com/dynamic/SymbolDirectory/"):
        try:
            r = requests.get(base + fname, headers=UA, timeout=10)
            if r.status_code != 200 or "|" not in r.text:
                log.warning(f"  NASDAQ 심볼 {fname} status={r.status_code} ({base})")
                continue
            added = 0
            for line in r.text.strip().split("\n")[1:-1]:
                p = line.split("|")
                if len(p) <= max(ec, tc, 1): continue
                sym = p[0].strip()
                is_test = len(p) > tc and p[tc].strip() == "Y"
                is_etf  = len(p) > ec and p[ec].strip() == "Y"
                if not sym or is_test or not sym.replace("-", "").isalpha(): continue
                if is_etf and sym not in US_MAJOR_ETFS: continue
                tickers.add(sym); exchange_map[sym] = exch_name
                security_names[sym] = p[1].strip() if len(p) > 1 else sym
                etf_flags[sym] = is_etf
                added += 1
            log.info(f"  NASDAQ 심볼 {fname}: {added}개 ({base})")
            return True
        except Exception as e:
            log.warning(f"  NASDAQ 심볼 {fname} 실패 ({base}): {e}")
    return False

def get_us_tickers():
    tickers=set(); exchange_map={}; sp500_set=set()
    security_names={}; etf_flags={}
    # 컬럼 인덱스: nasdaqlisted.txt = Symbol|Security Name|Market Category|Test Issue|
    #   Financial Status|Round Lot Size|ETF|NextShares (ETF=6, Test=3)
    # otherlisted.txt = ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|
    #   Test Issue|NASDAQ Symbol (ETF=4, Test=6)
    _load_nasdaq_symbol_file("nasdaqlisted.txt", 6, 3, "NASDAQ", tickers, exchange_map, security_names, etf_flags)
    _load_nasdaq_symbol_file("otherlisted.txt",  4, 6, "NYSE",   tickers, exchange_map, security_names, etf_flags)
    try:
        import pandas as pd
        r=requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",headers=UA,timeout=20)
        df=pd.read_html(io.StringIO(r.text))[0]
        for s in df["Symbol"].tolist():
            sym=str(s).replace(".","-"); tickers.add(sym); sp500_set.add(sym)
            etf_flags.setdefault(sym, False)   # S&P500 구성종목은 전부 일반주
    except: pass
    # 미국 본토 주요 ETF: 심볼 파일 성공 여부와 무관하게 항상 포함 (QQQ 등)
    for sym, nm in US_MAJOR_ETFS.items():
        tickers.add(sym); security_names[sym] = nm
        etf_flags[sym] = True; exchange_map[sym] = "ETF"
    log.info(f"미국 {len(tickers)}종목 (주요 ETF {len(US_MAJOR_ETFS)}개 포함)")
    return sorted(tickers),exchange_map,sp500_set,security_names,etf_flags

US_BOND_ETF_KEYWORDS = ("BOND","TREASURY","MUNICIPAL","MUNI ","T-BILL","TIPS",
                        "HIGH YIELD BOND","CORPORATE BOND","AGGREGATE BOND",
                        "DURATION BOND","FIXED INCOME")

def get_us_ath(usd_krw):
    tickers,exchange_map,sp500_set,security_names,etf_flags=get_us_tickers()
    if not tickers: return []
    d1=dl(tickers,"1y",chunk=100,sleep=1.0)
    cands=[tk for tk,s in d1.items() if len(s)>=2 and float(s.iloc[-1])>=float(s.max())*0.90]
    log.info(f"미국 1단계후보:{len(cands)}")
    if not cands: return []
    d2=dl(cands,"max",chunk=25,sleep=2.0)
    out=[]
    for tk,s in d2.items():
        try:
            last=float(s.iloc[-1]); prev=float(s.iloc[-2]); ath=float(s.max())
            if last>=ath*0.90:
                sec_name = security_names.get(tk, tk)
                is_etf = etf_flags.get(tk, False)
                if is_etf and any(kw in sec_name.upper() for kw in US_BOND_ETF_KEYWORDS):
                    continue   # 채권형 ETF만 제외, 주식형 ETF는 통과
                mcap=None
                try:
                    m=getattr(yf.Ticker(tk).fast_info,"market_cap",None) or 0
                    if m>0: mcap=round(m*usd_krw/1e12,1)
                except: pass
                # 지수 레이블
                idx=[]
                if tk in DOW30: idx.append("Dow")
                if tk in sp500_set: idx.append("S&P500")
                idx.append(exchange_map.get(tk,"NYSE"))
                url=f"https://m.stock.naver.com/worldstock/stock/{tk}/total"
                perf={}
                if is_etf:
                    try:
                        dts=[d.date() for d in s.index]
                        c1,c3,c5,c10,cumulative,fd=_calc_perf(dts,[float(x) for x in s.tolist()])
                        perf={"cagr1y":c1,"cagr3y":c3,"cagr5y":c5,"cagr10y":c10,
                              "cumulative_return":cumulative,
                              "first_date":fd.isoformat() if fd else None}
                    except Exception:
                        perf={}
                out.append({"ticker":tk,"name":sec_name if is_etf else tk,
                            "asset_type":"ETF" if is_etf else "주식",
                            "price":round(last,2),
                            "change":round((last-prev)/prev*100,2),
                            "gap":round((last-ath)/ath*100,2),"mcap":mcap,
                            "index":idx,"industry":None,
                            "market":"US","url":url, **perf})
        except: pass
    if out:
        log.info(f"미국 업종 조회 중 ({len(out)}종목)...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs={ex.submit(get_us_industry,s["ticker"]):s for s in out}
            for fut in as_completed(futs):
                s=futs[fut]
                try: s["industry"]=fut.result()
                except: s["industry"]=None
    etf_items=[s for s in out if s["asset_type"]=="ETF"]
    if etf_items:
        log.info(f"미국 ETF 상세 조회 중 ({len(etf_items)}종목)...")
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs={ex.submit(enrich_us_etf,s["ticker"],s["name"],usd_krw):s for s in etf_items}
            for fut in as_completed(futs):
                s=futs[fut]
                try: s.update(fut.result())
                except Exception: pass
        for s in etf_items:
            s.setdefault("etf_kind", classify_us_etf(s["name"], None))
            s.setdefault("aum", s.get("mcap"))
            s.setdefault("inception", s.get("first_date"))
        log.info(f"미국 ETF 상세 결과: 운용사 {sum(1 for s in etf_items if s.get('issuer'))}/{len(etf_items)}, "
                 f"추종지수 {sum(1 for s in etf_items if s.get('etf_index'))}/{len(etf_items)}")
    out.sort(key=lambda x:x["gap"])
    log.info(f"미국 최종:{len(out)}"); return out

# ── 한국: Naver Finance 전용 (yfinance .KS/.KQ, FDR, KRX API 전부 미사용) ──
# 근거: finance.naver.com은 이미 업종 조회로 접속 성공이 확인됐고,
#       yfinance .KS/.KQ 배치·FDR·data.krx.co.kr 은 GitHub Actions에서 반복적으로 0건 반환됨.
def _kr_market_stock_page(market_type: str, start_idx: int, page_size: int = 100):
    """
    새 stock.naver.com JSON API 페이지 조회.
    (구 finance.naver.com/sise/sise_market_sum.naver HTML 페이지는 SPA로 전면 개편되어
     <table> 태그가 응답에 아예 없어짐 — 2026-09-15 진단 로그로 확인됨.
     신버전은 stock.naver.com/api/domestic/market/stock/default JSON을 사용.)
    반환: (rows: list[dict], raw_top_level_keys: list|None — 파싱 실패시 진단용)
    """
    url = "https://stock.naver.com/api/domestic/market/stock/default"
    params = {
        "tradeType": "KRX",
        "marketType": market_type,      # "KOSPI" 또는 "KOSDAQ"
        "orderType": "marketSum",       # 시가총액 순
        "startIdx": start_idx,
        "pageSize": page_size,
    }
    r = requests.get(url, headers=UA, params=params, timeout=15)

    log.info(f"  [진단p] {market_type} startIdx={start_idx} status={r.status_code} 응답길이={len(r.text)}")

    if r.status_code != 200:
        return [], None

    try:
        data = r.json()
    except Exception as e:
        log.warning(f"  [진단p] {market_type} startIdx={start_idx} JSON파싱실패: {e} body일부={r.text[:200]}")
        return [], None

    # 응답 최상위 구조 후보 탐색 (list 직접 반환 또는 흔한 wrapper 키들)
    rows = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("stockList","list","items","data","content","stocks","result"):
            v = data.get(key)
            if isinstance(v, list):
                rows = v
                break
        if rows is None:
            log.info(f"  [진단p] {market_type} startIdx={start_idx} 응답 최상위 키: {list(data.keys())[:15]}")

    log.info(f"  [진단p] {market_type} startIdx={start_idx} rows개수={len(rows) if rows else 0}")
    return (rows or []), None


def _parse_kr_stock_row(row: dict):
    """itemcode/itemname/marketSum 등 문서화된 필드명 기준 파싱. 실패시 None."""
    try:
        code = str(row.get("itemcode") or row.get("code") or row.get("itemCode") or "").strip()
        name = str(row.get("itemname") or row.get("name") or row.get("itemName") or "").strip()
        if not code or not name:
            return None

        mcap = None
        raw_mcap = row.get("marketSum")
        if raw_mcap is not None:
            try:
                v = float(str(raw_mcap).replace(",", ""))
                if v > 0:
                    mcap = round(v / 1e12, 1)   # 원(raw) -> 조원. 기존 '억원' 가정이 틀려서
                                                 # 시가총액이 비정상적으로 크게 나왔던 원인이었음
            except Exception:
                pass

        return {"code": code, "name": name, "mcap": mcap, "_raw_mcap": raw_mcap}
    except Exception:
        return None


def get_kr_universe() -> dict:
    """{code: {"name":..., "mcap":..., "market":"KOSPI"|"KOSDAQ"}} — stock.naver.com JSON API 전량 순회"""
    universe = {}
    page_size = 100

    for market_type in ("KOSPI", "KOSDAQ"):
        start_idx = 0
        collected = 0
        for _ in range(60):   # 안전판: 최대 60페이지(=6000종목)까지만
            try:
                rows, _ = _kr_market_stock_page(market_type, start_idx, page_size)
            except Exception as e:
                log.error(f"{market_type} startIdx={start_idx} 요청 실패: {e}")
                rows = []

            if not rows:
                break

            for i, row in enumerate(rows):
                parsed = _parse_kr_stock_row(row)
                if parsed:
                    if start_idx == 0 and i == 0:
                        log.info(f"  [진단mcap] {market_type} 1위 {parsed['name']}({parsed['code']}) "
                                 f"raw_marketSum={parsed.get('_raw_mcap')} -> 변환후={parsed['mcap']}조")
                    universe[parsed["code"]] = {
                        "name": parsed["name"],
                        "mcap": parsed["mcap"],
                        "market": market_type,
                    }
                    collected += 1

            if len(rows) < page_size:
                break   # 마지막 페이지

            start_idx += page_size
            time.sleep(0.2)

        log.info(f"{market_type}: {collected}종목 (stock.naver.com JSON)")

    log.info(f"한국 전체 유니버스: {len(universe)}종목")
    return universe

def _kr_price_history(code: str, count: int = 3000) -> list:
    """네이버 fchart에서 일별 종가 리스트(오래된->최신 순) 반환"""
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
        r = requests.get(url, headers=UA, timeout=15)
        items = re.findall(r"""data=['"]([^'"]+)['"]""", r.text)
        closes = []
        for it in items:
            parts = it.split("|")
            if len(parts) >= 5:
                try:
                    c = float(parts[4])
                    if c > 0: closes.append(c)
                except: pass
        return closes
    except Exception:
        return []

def _kr_price_history_dated(code: str, count: int = 8000):
    """네이버 fchart에서 (날짜 리스트, 종가 리스트) 반환 — ETF 1년·3년·5년·10년 및 누적수익률·설립일 계산용"""
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
        r = requests.get(url, headers=UA, timeout=20)
        items = re.findall(r"""data=['"]([^'"]+)['"]""", r.text)
        dates, closes = [], []
        for it in items:
            parts = it.split("|")
            if len(parts) >= 5:
                try:
                    c = float(parts[4])
                    d = datetime.strptime(parts[0], "%Y%m%d").date()
                    if c > 0:
                        dates.append(d); closes.append(c)
                except Exception:
                    pass
        return dates, closes
    except Exception:
        return [], []


def get_kr_ath(usd_krw, kr_last=None):
    universe = get_kr_universe()
    if not universe:
        log.warning("한국 종목 유니버스 1차 수집 실패 — 일시적 네트워크 문제일 수 있어 30초 후 재시도")
        time.sleep(30)
        universe = get_kr_universe()
    if not universe:
        log.error("한국 종목 유니버스 재시도까지 실패 — 0종목 반환 (네트워크 문제 지속 중일 가능성)")
        return []

    etf_universe = get_kr_etf_universe()
    for _code, _meta in etf_universe.items():
        if _code in universe:
            universe[_code]["is_etf"] = True
            if not universe[_code].get("mcap") and _meta.get("mcap"):
                universe[_code]["mcap"] = _meta["mcap"]
        else:
            universe[_code] = _meta
    log.info(f"한국 {len(universe)}종목 fchart 가격이력 조회 시작 (ETF {len(etf_universe)}종목 포함, 15 workers)...")

    def fetch_one(code, meta):
        name = meta["name"]
        if "스팩" in name:
            return None
        etf_flag = bool(meta.get("is_etf")) or kr_is_etf_name(name)
        dates = None
        if etf_flag:
            dates, closes = _kr_price_history_dated(code, count=8000)   # 설립일/1년·3년·5년·10년 및 누적수익률용 장기 이력
        else:
            closes = _kr_price_history(code, count=3000)
        if len(closes) < 30:
            return None
        last, prev, ath = closes[-1], closes[-2], max(closes)
        if last <= 0 or ath <= 0:
            return None
        if last >= ath * 0.90:
            res = {"ticker":code, "name":name, "price":int(last),
                   "change":round((last-prev)/prev*100,2),
                   "gap":round((last-ath)/ath*100,2),
                   "mcap":meta.get("mcap"),
                   "index":[meta.get("market","KR")], "industry":None,
                   "market":meta.get("market","KR"),
                   "is_etf":etf_flag,
                   "url":f"https://m.stock.naver.com/domestic/stock/{code}/total"}
            if etf_flag and dates and len(dates) == len(closes):
                c1, c3, c5, c10, cumulative, fd = _calc_perf(dates, closes)
                res.update({"cagr1y": c1, "cagr3y": c3, "cagr5y": c5, "cagr10y": c10,
                            "cumulative_return": cumulative,
                            "first_date": fd.isoformat() if fd else None})
            return res
        return None

    out = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(fetch_one, code, meta): code for code, meta in universe.items()}
        for fut in as_completed(futs):
            r = fut.result()
            if r: out.append(r)

    log.info(f"한국 ATH 후보: {len(out)}종목")

    if out:
        matched = sum(1 for s in out if s["ticker"] in KR_INDUSTRY_STATIC)
        log.info(f"한국 업종 조회 (정적표): {matched}/{len(out)}종목 매칭")
        for s in out:
            s["industry"] = KR_INDUSTRY_STATIC.get(s["ticker"])

    # ETF 판별: 국내 ETF 목록 API 소속이면 확정, 아니면 운용사 브랜드 접두사로 보조 판별.
    # 주식형·원자재 등 비채권 ETF는 통과시키고, 채권형 ETF만 이름 키워드로 제외.
    before_etf_filter = len(out)
    out = [s for s in out if not (s.get("is_etf") and kr_is_bond_etf(s["name"]))]
    log.info(f"채권 ETF 제외: {before_etf_filter}종목 → {len(out)}종목")

    for s in out:
        s["asset_type"] = "ETF" if s.get("is_etf") else "주식"

    etf_items = [s for s in out if s["asset_type"] == "ETF"]
    if etf_items:
        log.info(f"한국 ETF 상세 조회 중 ({len(etf_items)}종목)...")
        def enrich_kr(s):
            try:
                base = fetch_kr_etf_base(s["ticker"])
                parsed = parse_kr_etf_base(base) if base else {}
            except Exception:
                parsed = {}
            s["etf_index"] = parsed.get("etf_index")
            s["issuer"] = parsed.get("issuer") or kr_issuer_from_brand(s["name"])
            s["inception"] = parsed.get("inception") or s.get("first_date")
            s["aum"] = s.get("mcap")
            s["etf_kind"] = classify_kr_etf(s["name"])
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(enrich_kr, etf_items))
        log.info(f"한국 ETF 상세 결과: 추종지수 {sum(1 for s in etf_items if s.get('etf_index'))}/{len(etf_items)}, "
                 f"운용사 {sum(1 for s in etf_items if s.get('issuer'))}/{len(etf_items)}")

    out.sort(key=lambda x:x["gap"])
    log.info(f"한국 최종:{len(out)}")
    return out

# ── 이메일 ────────────────────────────────────────────
BADGE_COLOR={"Dow":"#e74c3c","S&P500":"#2980b9","NASDAQ":"#27ae60",
              "NYSE":"#7f8c8d","KOSPI":"#1a1a2e","KOSDAQ":"#8e44ad"}
def _badges(labels):
    if not labels: return ""
    return f"<div style='margin-top:2px;font-size:11px;color:#888'>{' · '.join(labels)}</div>"

def tbl_html(stocks,title,currency,holiday,date_s,hmsg="",flag=""):
    return email_layout.stocks_table(stocks, title, currency, holiday, date_s, hmsg)


def build_email(us,kr,info,usd_krw,new_us=None,new_kr=None,diag=None,indices=None,
                etf_info=None,include_all=False):
    return email_layout.render_email(us, kr, info, usd_krw, new_us, new_kr,
                                     diag, indices, etf_info, include_all)

def build_subject(info):
    ut=" [휴장]" if info["us_holiday"] else ""; kt=" [휴장]" if info["kr_holiday"] else ""
    return f"ATH & ETF | 미국 {info['us_last_str']}{ut} / 한국 {info['kr_last_str']}{kt}"


def compose_email_message(html, subject, user, to, report_html=None):
    """Related CID flags, a text fallback, and a complete report when body is shortened."""
    if len(html.encode("utf-8")) > email_layout.MAX_BODY_BYTES:
        raise ValueError("Email body exceeds safe size")
    msg = MIMEMultipart("mixed")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    related = MIMEMultipart("related")
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText("오늘의 ATH & ETF 리포트입니다. HTML 보기에서 국기와 ETF 수익률 카드를 확인하세요.", "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    related.attach(alternative)
    for country, png in email_flags.flag_images().items():
        asset = MIMEImage(png, _subtype="png")
        asset.add_header("Content-ID", f"<ath-flag-{country}>")
        asset.add_header("Content-Disposition", "inline", filename=f"flag-{country}.png")
        related.attach(asset)
    msg.attach(related)
    if report_html and report_html != html:
        report = MIMEText(email_flags.inline_flag_sources(report_html), "html", "utf-8")
        report.add_header("Content-Disposition", "attachment", filename="ATH-full-report.html")
        msg.attach(report)
    return msg


def send_email(html, subject, report_html=None):
    user=os.environ["GMAIL_USER"]; pwd=os.environ["GMAIL_APP_PASSWORD"]
    to=os.environ.get("RECIPIENT_EMAIL","ykhan@dacpole.com")
    msg = compose_email_message(html, subject, user, to, report_html)
    preview_dir = Path("work")
    preview_dir.mkdir(exist_ok=True)
    (preview_dir / "email-preview.html").write_text(email_flags.inline_flag_sources(html), encoding="utf-8")
    if report_html:
        (preview_dir / "email-full-report.html").write_text(email_flags.inline_flag_sources(report_html), encoding="utf-8")
    log.info(f"메일 레이아웃: 본문 {len(html.encode('utf-8')):,}바이트 / 전체리포트 {len((report_html or html).encode('utf-8')):,}바이트 / 국기 PNG 2개")
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as smtp:
        smtp.login(user,pwd); smtp.sendmail(user,to,msg.as_string())
    log.info(f"✅ 발송→{to}")

CODE_VERSION = "2026-10-08-compact-etf-comparison"

def main():
    log.info(f"=== ATH 리포트 시작 (코드버전: {CODE_VERSION}) ===")
    info=get_trading_info(); usd_krw=get_usd_krw(); indices=get_market_indices()
    us=get_us_ath(usd_krw)
    kr=get_kr_ath(usd_krw, info.get("kr_last"))

    # 거래일 기준 스냅샷 비교 (같은 거래일 재실행해도 항상 동일 결과)
    us_date_key = info["us_last"].isoformat() if info.get("us_last") else datetime.now(KST).strftime("%Y-%m-%d")
    kr_date_key = info["kr_last"].isoformat() if info.get("kr_last") else datetime.now(KST).strftime("%Y-%m-%d")

    snapshots = load_snapshots()
    us_days_before = len(snapshots.get('US',{}))
    kr_days_before = len(snapshots.get('KR',{}))
    log.info(f"불러온 스냅샷 누적 일수 — US: {us_days_before}일치, KR: {kr_days_before}일치 "
             f"(이 숫자가 매번 실행 후에도 늘지 않고 그대로면 캐시 저장이 실패하고 있다는 뜻)")
    new_us = compute_new_tickers(us, snapshots, "US", us_date_key)
    new_kr = compute_new_tickers(kr, snapshots, "KR", kr_date_key)
    log.info(f"신규 티커: US {len(new_us)}개, KR {len(new_kr)}개 (US기준일:{us_date_key} KR기준일:{kr_date_key})")

    # 누적 등장 횟수 (오늘 스냅샷이 이미 반영된 상태이므로 오늘 포함해서 카운트됨)
    us_streak = compute_streak_counts(snapshots, "US")
    kr_streak = compute_streak_counts(snapshots, "KR")
    for s in us: s["streak"] = us_streak.get(s["ticker"], 1)
    for s in kr: s["streak"] = kr_streak.get(s["ticker"], 1)

    # ETF 전용 섹션: ATH -10% 이내 ETF(한국+미국) 중 최근 1년 수익률 내림차순 20개
    etf_info = build_etf_info(us, kr)
    log.info(f"ETF 섹션: 풀 {etf_info['pool']}개 / 1년수익률 산출 {etf_info['with_ret']}개 / 표시 {len(etf_info['rows'])}개")

    diag = {"us_days_before": us_days_before, "kr_days_before": kr_days_before}
    email_html = build_email(us,kr,info,usd_krw,new_us,new_kr,diag,indices,etf_info)
    full_report = build_email(us,kr,info,usd_krw,new_us,new_kr,diag,indices,etf_info,include_all=True)
    send_email(email_html, build_subject(info), full_report)

    # 스냅샷 저장 (Actions Cache로 다음 실행에 전달됨)
    save_snapshots(snapshots)
    log.info(f"=== 완료: US{len(us)} KR{len(kr)} / 신규 US{len(new_us)} KR{len(new_kr)} ===")

if __name__=="__main__": main()
