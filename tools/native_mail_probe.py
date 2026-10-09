import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bs4 import BeautifulSoup
from src import main,email_layout
email_layout.MAX_EMAIL_BYTES=500000
main.main(prepare_only=True)
source=Path("work/email-body.html").read_text(encoding="utf-8")
doc=BeautifulSoup(source,"html5lib")
result={"raw":len(source.encode()),"canonical":len(str(doc).encode()),"sections":{}}
for key in ("us","kr","new","returns"):
    table=doc.find("table",id=key)
    result["sections"][key]={"bytes":len(str(table).encode()) if table else 0,"rows":len(table.select("tbody tr")) if table else 0}
print("NATIVE_MEASURE:"+json.dumps(result),flush=True)
print("NATIVE_SOURCE_JSON:"+json.dumps(source,ensure_ascii=True),flush=True)
