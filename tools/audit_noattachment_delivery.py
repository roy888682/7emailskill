import os,json,re,imaplib,smtplib,ssl,email,hashlib
from email.utils import make_msgid,formatdate,getaddresses
from email.header import decode_header,make_header
from email.policy import SMTP
EXPECTED="ykhan@dacpole.com"
user=os.environ["GMAIL_USER"];pwd=os.environ["GMAIL_APP_PASSWORD"]
assert os.environ.get("RECIPIENT_EMAIL",EXPECTED)==EXPECTED
c=imaplib.IMAP4_SSL("imap.gmail.com",993,ssl_context=ssl.create_default_context(),timeout=35)
c.login(user,pwd)
typ,rows=c.list()
box=None
for row in rows:
    m=re.match(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(.+)',row or b"")
    if m and b"\\Sent" in m[1].split():box=m[2].decode("ascii")
assert box
c.select(box,readonly=True)
query='in:sent to:'+EXPECTED+' rfc822msgid:179331504799.5087.4810777806026327886@runnervm48cm3.f21uuyqt0vlu5czq0hxzcz2hua.bx.internal.cloudapp.net'
typ,ids=c.uid("search",None,"X-GM-RAW",'"'+query+'"')
assert typ=="OK" and len(ids[0].split())==1,"Original report must match exactly once"
typ,data=c.uid("fetch",ids[0].split()[0],"(BODY.PEEK[])")
raw=next(x[1] for x in data if isinstance(x,tuple))
original=email.message_from_bytes(raw,policy=SMTP)
assert [a.lower() for _,a in getaddresses(original.get_all("To",[]))]==[EXPECTED]
original_html=[p.get_payload(decode=True) for p in original.walk() if p.get_content_type()=="text/html"]
assert len(original_html)==1
attachments=[p for p in original.walk() if p.get_content_disposition()=="attachment"]
assert len(attachments)==1 and attachments[0].get_filename()=="ath-full-report.html"
assert original.get_content_type()=="multipart/mixed"
parts=original.get_payload()
assert len(parts)==2 and parts[0].get_content_type()=="multipart/related"
msg=parts[0]
for name in ("From","To","Subject","Date","Message-ID"):
    if msg.get(name):del msg[name]
msg["From"]=user;msg["To"]=EXPECTED
msg["Subject"]="[ATH 리포트 재전송·첨부 없음] 미국·한국 2026-10-29 전체종목"
msg["Date"]=formatdate(localtime=False);msg["Message-ID"]=make_msgid(domain="gmail.com")
new_html=[p.get_payload(decode=True) for p in msg.walk() if p.get_content_type()=="text/html"]
assert new_html==original_html,"The complete accepted body must remain byte-for-byte identical"
assert not any(p.get_content_disposition()=="attachment" for p in msg.walk())
wire=msg.as_bytes(policy=SMTP)
assert max(map(len,wire.split(b"\r\n")))<=998
proof={"original_html_sha256":hashlib.sha256(original_html[0]).hexdigest(),"resend_html_sha256":hashlib.sha256(new_html[0]).hexdigest(),"all_report_rows_preserved":True,"original_wire_bytes":len(raw),"wire_bytes":len(wire),"removed_attachments":1,"message_id":msg["Message-ID"],"subject":str(msg["Subject"])}
c.logout()
with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=45) as smtp:
    smtp.ehlo()
    assert smtp.has_extn("8bitmime")
    smtp.login(user,pwd)
    code,reply=smtp.mail(user,options=("BODY=8BITMIME",))
    assert code==250
    code,reply=smtp.rcpt(EXPECTED)
    assert code in (250,251)
    code,reply=smtp.data(wire)
    proof.update(smtp_code=code,smtp_reply=reply.decode(errors="replace").replace(user,"[sender]")[:250])
    print("REPORT_WITHOUT_ATTACHMENT:"+json.dumps(proof,ensure_ascii=False),flush=True)
    assert code==250
