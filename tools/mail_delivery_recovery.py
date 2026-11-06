"""Check only the missing ATH report and send one small delivery probe."""
import email
import email.header
import imaplib
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses, make_msgid
from pathlib import Path

TARGET = "ykhan@dacpole.com"
ORIGINAL_ID = "<179395669630.4580.11777284733817646498@gmail.com>"
SENDER = os.environ["GMAIL_USER"]
PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
configured = getaddresses([os.environ.get("RECIPIENT_EMAIL", TARGET)])
if len(configured) != 1 or configured[0][1].casefold() != TARGET:
    raise RuntimeError("The configured recipient differs from the requested recipient")

result = {"target_matches_expected": True,
          "sender_matches_connected_gmail": SENDER.casefold() == "hansharedid@gmail.com",
          "original_message_id": ORIGINAL_ID, "mailbox_trace": {}}

def quoted(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

def decoded(value):
    return str(email.header.make_header(email.header.decode_header(value or "")))

def folders(client):
    status, values = client.list()
    selected = {"INBOX": b"INBOX"}
    if status != "OK":
        return selected
    for item in values:
        match = re.match(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(.+)', item or b"")
        if not match:
            continue
        for flag in (b"\\All", b"\\Sent", b"\\Junk"):
            if flag in match[1].split():
                selected[flag.decode("ascii")] = match[2]
    return selected

def search(client, query):
    status, values = client.uid("search", None, "X-GM-RAW", quoted(query))
    if status != "OK":
        return []
    return (values[0] or b"").split()

def payload(values):
    return b"".join(item[1] for item in values if isinstance(item, tuple) and isinstance(item[1], bytes))

def trace_mailbox():
    trace = {"original_sent_matches": [], "matching_delivery_reports": [],
             "folders_checked": [], "errors": []}
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30) as client:
            client.login(SENDER, PASSWORD)
            available = folders(client)
            visited = set()
            for label, folder in available.items():
                if folder in visited:
                    continue
                visited.add(folder)
                try:
                    status, _ = client.select(folder, readonly=True)
                    if status != "OK":
                        continue
                    trace["folders_checked"].append(label)
                    ids = search(client, "rfc822msgid:" + ORIGINAL_ID.strip("<>"))
                    for uid in ids[-3:]:
                        status, values = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (TO DATE SUBJECT MESSAGE-ID)])")
                        if status != "OK":
                            continue
                        message = email.message_from_bytes(payload(values))
                        trace["original_sent_matches"].append({
                            "folder": label, "message_id": message.get("Message-ID"),
                            "date": message.get("Date"),
                            "subject": decoded(message.get("Subject")),
                            "to_matches_expected": [addr.casefold() for _, addr in getaddresses(message.get_all("To", []))] == [TARGET]})
                    bounce_query = 'after:2026/11/06 (from:mailer-daemon OR from:postmaster) "' + TARGET + '"'
                    for uid in search(client, bounce_query)[-10:]:
                        status, values = client.uid("fetch", uid, "(BODY.PEEK[]<0.131072>)")
                        if status != "OK":
                            continue
                        raw = payload(values)
                        message = email.message_from_bytes(raw)
                        text = raw.decode("utf-8", errors="replace")
                        if TARGET.casefold() not in text.casefold():
                            continue
                        statuses = []
                        for part in message.walk():
                            if part.get_content_type() == "message/delivery-status":
                                for block in part.get_payload():
                                    status_item = {key: block.get(key) for key in ("Action", "Status", "Remote-MTA", "Diagnostic-Code") if block.get(key)}
                                    if status_item:
                                        statuses.append(status_item)
                        trace["matching_delivery_reports"].append({
                            "date": message.get("Date"), "subject": decoded(message.get("Subject")),
                            "references_original": ORIGINAL_ID.strip("<>") in text,
                            "statuses": statuses,
                            "status_codes": sorted(set(re.findall(r"\b[245]\.\d{1,3}\.\d{1,3}\b", text)))[:10]})
                except Exception as error:
                    trace["errors"].append({"folder": label, "type": type(error).__name__})
    except Exception as error:
        trace["connection_error_type"] = type(error).__name__
    return trace

result["mailbox_trace"] = trace_mailbox()
print("ATH_DELIVERY_MAILBOX_TRACE:" + json.dumps(result, ensure_ascii=False), flush=True)

class QueueReceiptSMTP(smtplib.SMTP_SSL):
    def data(self, message):
        response = super().data(message)
        self.queue_response = response
        return response

now = datetime.now(timezone.utc)
kst = now.astimezone(timezone(timedelta(hours=9)))
probe = EmailMessage(policy=SMTP)
probe["From"], probe["To"] = SENDER, TARGET
probe["Date"] = email.utils.format_datetime(now)
probe["Message-ID"] = make_msgid(domain=SENDER.rsplit("@", 1)[-1])
probe["Subject"] = "[ATH 수신 경로 점검] " + kst.strftime("%m-%d %H:%M KST") + " 진단 메일"
probe.set_content("이 메일은 요청하신 수신 경로 점검을 위한 짧은 진단 메일입니다.\n"
                  "11월 6일 18:18에 발송한 전체 리포트가 도착하지 않아 발송 계정의 반송 기록과 수신 경로를 점검하고 있습니다.\n"
                  "이 진단 메일의 도착 여부를 Codex 대화에 알려주시면 다음 점검에 반영하겠습니다.\n",
                  charset="utf-8", cte="quoted-printable")
wire = probe.as_bytes()
with QueueReceiptSMTP("smtp.gmail.com", 465, timeout=30, context=ssl.create_default_context()) as smtp:
    smtp.ehlo()
    smtp.login(SENDER, PASSWORD)
    refused = smtp.sendmail(SENDER, TARGET, wire)
    if refused:
        raise RuntimeError("The diagnostic recipient was refused")
    code, response = smtp.queue_response
    if code != 250:
        raise RuntimeError("The diagnostic message was not queued")
result["diagnostic"] = {
    "message_id": probe["Message-ID"],
    "subject": str(probe["Subject"]),
    "accepted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "recipient_matches_expected": True, "wire_bytes": len(wire),
    "attachment_count": 0, "smtp_data_code": code,
    "smtp_queue_response": response.decode("ascii", errors="replace")[:300],
    "inbox_delivery_verified": False}
print("ATH_DELIVERY_DIAGNOSTIC_ACCEPTED:" + json.dumps(result["diagnostic"], ensure_ascii=False), flush=True)
Path("work").mkdir(exist_ok=True)
Path("work/mail-path-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


import hashlib

if any(item.get('references_original') and any(str(s.get('Status', '')).startswith('5.') for s in item.get('statuses', [])) for item in result['mailbox_trace'].get('matching_delivery_reports', [])):
    raise RuntimeError('A permanent delivery report refers to the original message; inspect the audit before resending the full report')

with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30) as client:
    client.login(SENDER, PASSWORD)
    sent = folders(client).get("\\Sent")
    if sent is None or client.select(sent, readonly=True)[0] != "OK":
        raise RuntimeError("The sender Sent folder is unavailable")
    ids = search(client, "rfc822msgid:" + ORIGINAL_ID.strip("<>"))
    if len(ids) != 1:
        raise RuntimeError("The exact original report could not be uniquely identified")
    status, values = client.uid("fetch", ids[0], "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError("The original report could not be read")
    message = email.message_from_bytes(payload(values), policy=SMTP)

html_parts = [part for part in message.walk() if part.get_content_type() == "text/html"]
if len(html_parts) != 1 or any(part.get_content_disposition() == "attachment" for part in message.walk()):
    raise RuntimeError("The original report's MIME structure differs")
body = html_parts[0].get_payload(decode=True).decode("utf-8").replace("\r\n", "\n")
body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
if body_hash != "8d9f0e9988b0995a19c169321a23c92a1f9665760b1083c9e917a10f491936bf":
    raise RuntimeError("The original report differs from its validated SMTP receipt")
if [addr.casefold() for _, addr in getaddresses(message.get_all("To", []))] != [TARGET]:
    raise RuntimeError("The original report recipient differs")

Path("work/recovered-report.html").write_text(body, encoding="utf-8")

for header in ("Subject", "Date", "Message-ID", "Return-Path", "Received",
               "DKIM-Signature", "ARC-Seal", "ARC-Message-Signature",
               "ARC-Authentication-Results", "Authentication-Results",
               "Delivered-To", "X-Google-Smtp-Source", "X-Received"):
    while message.get(header) is not None:
        del message[header]
now = datetime.now(timezone.utc)
kst = now.astimezone(timezone(timedelta(hours=9)))
message["Subject"] = "[ATH 전체 리포트 재전송] " + kst.strftime("%m-%d %H:%M KST") + " · 11-05 기준 · ETF 987개"
message["Date"] = email.utils.format_datetime(now)
message["Message-ID"] = make_msgid(domain=SENDER.rsplit("@", 1)[-1])
wire = message.as_bytes(policy=SMTP)
roundtrip = email.message_from_bytes(wire, policy=SMTP)
sent_html = [part for part in roundtrip.walk() if part.get_content_type() == "text/html"]
if len(sent_html) != 1 or hashlib.sha256(sent_html[0].get_payload(decode=True).decode("utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest() != body_hash:
    raise RuntimeError("Reserialization changed the report body")

class QueueReceiptSMTP(smtplib.SMTP_SSL):
    def data(self, value):
        response = super().data(value)
        self.queue_response = response
        return response

with QueueReceiptSMTP("smtp.gmail.com", 465, timeout=60, context=ssl.create_default_context()) as smtp:
    smtp.ehlo()
    if not smtp.has_extn("8bitmime"):
        raise RuntimeError("The SMTP relay lacks the report's required MIME extension")
    smtp.login(SENDER, PASSWORD)
    refused = smtp.sendmail(SENDER, TARGET, wire, mail_options=("BODY=8BITMIME",))
    if refused:
        raise RuntimeError("The report recipient was refused")
    code, response = smtp.queue_response
    if code != 250:
        raise RuntimeError("The report was not queued")
resend = {
    "message_id": message["Message-ID"], "subject": str(message["Subject"]),
    "accepted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "recipient_matches_expected": True, "body_bytes": len(body.encode("utf-8")),
    "wire_bytes": len(wire), "attachment_count": 0, "unchanged_validated_body": True,
    "body_sha256": body_hash, "smtp_data_code": code,
    "smtp_queue_response": response.decode("ascii", errors="replace")[:300],
    "inbox_delivery_verified": False}
print("ATH_FULL_REPORT_RESEND_ACCEPTED:" + json.dumps(resend, ensure_ascii=False), flush=True)
Path("work").mkdir(exist_ok=True)
result["resend"] = resend
Path("work/mail-path-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
