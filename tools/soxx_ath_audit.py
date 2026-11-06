import json
from src.us_naver_links import verified_close
for day in ("2026-11-04", "2026-11-05"):
    print("SOXX_VERIFIED_NAVER_CLOSE:"+json.dumps(verified_close("SOXX", "https://m.stock.naver.com/worldstock/etf/SOXX.O", day), ensure_ascii=False), flush=True)
