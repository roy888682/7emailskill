"""Read only size/structure diagnostics for the user's clipped Gmail message."""
import imaplib
import os
from email import message_from_bytes
from bs4 import BeautifulSoup
import hashlib
import json
import re

def main():
    user=os.environ["GMAIL_USER"]
    password=os.environ["GMAIL_APP_PASSWORD"]
    recipient=os.environ.get("RECIPIENT_EMAIL","ykhan@dacpole.com")
    result={"account_is_recipient":user.casefold()==recipient.casefold(),"target_accessible":False}
    with imaplib.IMAP4_SSL("imap.gmail.com",993) as mailbox:
        mailbox.login(user,password)
        status,folders=mailbox.list()
        all_folder=None
        for entry in folders or []:
            if entry and b"\\All" in entry:
                all_folder=entry.rsplit(b' "/" ',1)[-1]
                break
        if all_folder is None:
            all_folder=b'"[Gmail]/All Mail"'
        status,_=mailbox.select(all_folder,readonly=True)
        if status!="OK":
            raise RuntimeError("Could not open the read-only All Mail mailbox")
        status,found=mailbox.uid("search",None,"X-GM-MSGID","1878572327997601042")
        requested=bool(status=="OK" and found and found[0])
        if not requested:
            query=f'"in:sent subject:ATH to:{recipient} after:2026/10/08"'
            status,found=mailbox.uid("search",None,"X-GM-RAW",query)
        result["copy"]="requested_received" if requested else "sender_sent"
        if status=="OK" and found and found[0]:
            uid=found[0].split()[-1]
            status,items=mailbox.uid("fetch",uid,"(BODY.PEEK[])")
            raw=next(item[1] for item in items if isinstance(item,tuple))
            msg=message_from_bytes(raw)
            html_parts=[p for p in msg.walk() if p.get_content_type()=="text/html"]
            result.update(target_accessible=requested,copy_accessible=True,raw_bytes=len(raw),
                          part_encodings=[{"type":p.get_content_type(),"cte":p.get("Content-Transfer-Encoding"),
                                           "decoded_bytes":len(p.get_payload(decode=True) or b"")}
                                          for p in msg.walk() if not p.is_multipart()])
            for part in html_parts:
                payload=part.get_payload(decode=True)
                html=payload.decode(part.get_content_charset() or "utf-8")
                doc=BeautifulSoup(html,"html5lib")
                result["html"]={"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),
                                "canonical_utf8_bytes":len(str(doc).encode("utf-8")),
                                "table_rows":{key:len(doc.select("#"+key+" tbody tr")) for key in ("us","kr","new","returns")},
                                "links":len(doc.select("a[href]")),
                                "href_bytes":sum(len(str(a["href"]).encode("utf-8"))+8 for a in doc.select("a[href]")),
                                "cid_images":len(doc.select('img[src^="cid:"]')),
                                "images":len(doc.select("img")),
                                "clipping_text_in_source":"메일 내용 잘림" in html or "Message clipped" in html}
        print("RECEIVED_DIAGNOSTICS:"+json.dumps(result,ensure_ascii=False),flush=True)
        mailbox.logout()

if __name__=="__main__":
    main()
