import os, json, re, imaplib, smtplib, ssl, email, hashlib
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid, formatdate
from email.header import decode_header, make_header
from datetime import datetime, timezone
EXPECTED = "ykhan@dacpole.com"
user = os.environ["GMAIL_USER"]
pwd = os.environ["GMAIL_APP_PASSWORD"]
raw_to = os.environ.get("RECIPIENT_EMAIL", EXPECTED)
parsed = [address for _, address in getaddresses([raw_to])]
config = {"recipient_exact_match": raw_to == EXPECTED,
          "recipient_trimmed_match": raw_to.strip().lower() == EXPECTED,
          "recipient_count": len(parsed), "single_recipient_expected": parsed == [EXPECTED],
          "sender_matches_connected_gmail": user.lower() == "hansharedid@gmail.com"}
print("DELIVERY_CONFIG:"+json.dumps(config), flush=True)
if parsed != [EXPECTED] or raw_to.strip().lower() != EXPECTED:
    raise RuntimeError("Configured recipient differs from the explicitly requested recipient")
def decoded(value):
    try: return str(make_header(decode_header(value or "")))
    except Exception: return "[header decoding failed]"
client = None
def mailbox(flag):
    typ, rows = client.list()
    if typ != "OK": raise RuntimeError("Cannot list mailbox flags")
    for row in rows:
        if not row: continue
        match = re.match(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(.+)', row)
        if match and flag.encode() in match[1].split():
            return match[2].decode("ascii")
    raise RuntimeError("Required mailbox flag was not found")
def search(query):
    typ, rows = client.uid("search", None, "X-GM-RAW", '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"')
    if typ != "OK": raise RuntimeError("Focused mailbox search failed")
    return (rows[0] or b"").split()
def read_headers(uid):
    typ, data = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (DATE FROM TO SUBJECT MESSAGE-ID CONTENT-TYPE)])")
    raw = next((item[1] for item in data if isinstance(item,tuple)), b"")
    if typ != "OK" or not raw: raise RuntimeError("Cannot read matching message headers")
    msg = email.message_from_bytes(raw)
    tos = [addr.lower() for _,addr in getaddresses(msg.get_all("To",[]))]
    return {"date":msg.get("Date"),"subject":decoded(msg.get("Subject"))[:200],
            "message_id":msg.get("Message-ID"),"to_expected":EXPECTED in tos,
            "content_type":msg.get_content_type()}
try:
    client = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=35)
    client.login(user,pwd)
    typ,_ = client.select(mailbox(r"\Sent"), readonly=True)
    if typ != "OK": raise RuntimeError("Sent mailbox cannot be selected read-only")
    ids = search("in:sent to:"+EXPECTED+" newer_than:3d")
    print("SENT_REPORTS:"+json.dumps({"matches":len(ids),"recent":[read_headers(uid) for uid in ids[-5:]]},ensure_ascii=False),flush=True)
    typ,_=client.select(mailbox(r"\All"), readonly=True)
    if typ != "OK": raise RuntimeError("All-mail mailbox cannot be selected read-only")
    ids=search('in:anywhere newer_than:3d "'+EXPECTED+'" (from:mailer-daemon OR from:postmaster)')
    bounced=[]
    for uid in ids[-10:]:
        typ,data=client.uid("fetch",uid,"(BODY.PEEK[])")
        raw=next((item[1] for item in data if isinstance(item,tuple)),b"")
        if typ!="OK" or EXPECTED.encode() not in raw.lower(): continue
        msg=email.message_from_bytes(raw)
        result={"date":msg.get("Date"),"subject":decoded(msg.get("Subject"))[:200],"message_id":msg.get("Message-ID"),"dsn":[]}
        for part in msg.walk():
            if part.get_content_type()=="message/delivery-status":
                for block in part.get_payload():
                    fields={key:block.get(key) for key in ("Final-Recipient","Original-Recipient","Action","Status","Diagnostic-Code","Remote-MTA","Last-Attempt-Date") if block.get(key)}
                    if fields: result["dsn"].append(fields)
        if not result["dsn"]:
            texts=[]
            for part in msg.walk():
                if part.get_content_type()=="text/plain":
                    payload=part.get_payload(decode=True) or b""
                    text=payload.decode(part.get_content_charset() or "utf-8",errors="replace")
                    texts.extend(line.strip()[:350] for line in text.splitlines() if re.search(r"([245]\.\d\.\d|blocked|reject|quarantin|not delivered|delivery.*fail|ykhan@dacpole)",line,re.I))
            result["diagnostic_lines"]=texts[:8]
        bounced.append(result)
    print("BOUNCE_AUDIT:"+json.dumps({"matches":len(ids),"records":bounced},ensure_ascii=False),flush=True)
except Exception as exc:
    print("MAILBOX_AUDIT_ERROR:"+json.dumps({"type":type(exc).__name__,"detail":str(exc).replace(user,"[sender]").replace(pwd,"[password]")[:240]}),flush=True)
finally:
    if client:
        try: client.logout()
        except Exception: pass
msg=EmailMessage()
msg["From"]=user
msg["To"]=EXPECTED
msg["Subject"]="[ATH 수신 경로 점검] 첨부 없는 진단 메일 "+datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
msg["Date"]=formatdate(localtime=False)
msg["Message-ID"]=make_msgid(domain="gmail.com")
msg.set_content("주식 리포트 이메일의 수신 경로를 점검하기 위한 진단 메일입니다.\n첨부파일 없이 짧은 일반 텍스트로 보냅니다.\n이 메일이 도착했는지 Codex 대화에서 알려 주세요.\n",charset="utf-8",cte="base64")
wire=msg.as_bytes(policy=email.policy.SMTP)
with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=45) as smtp:
    code,_=smtp.ehlo()
    smtp.login(user,pwd)
    code,reply=smtp.mail(user,options=())
    if code!=250: raise RuntimeError("Diagnostic SMTP MAIL FROM rejected")
    code,reply=smtp.rcpt(EXPECTED)
    print("PLAIN_TEST_RECIPIENT:"+json.dumps({"smtp_code":code,"reply":reply.decode(errors="replace").replace(user,"[sender]")[:200]}),flush=True)
    if code not in (250,251): raise RuntimeError("Diagnostic SMTP recipient rejected")
    code,reply=smtp.data(wire)
    print("PLAIN_TEST_DATA:"+json.dumps({"smtp_code":code,"reply":reply.decode(errors="replace").replace(user,"[sender]")[:250],"message_id":msg["Message-ID"],"subject":msg["Subject"],"wire_bytes":len(wire),"sha256":hashlib.sha256(wire).hexdigest()}),flush=True)
    if code!=250: raise RuntimeError("Diagnostic SMTP DATA rejected")
