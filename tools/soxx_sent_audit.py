import email
import imaplib
import json
import os
import re
from html.parser import HTMLParser
from email.policy import default
from email.header import decode_header, make_header

MESSAGE_ID = "<179393210000.4408.1652338671088769288@gmail.com>"
from bs4 import BeautifulSoup

user = os.environ["GMAIL_USER"]
with imaplib.IMAP4_SSL("imap.gmail.com", timeout=30) as client:
    client.login(user, os.environ["GMAIL_APP_PASSWORD"])
    status, folders = client.list()
    sent = None
    for value in folders:
        match = re.match(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(.+)', value or b"")
        if match and b"\\Sent" in match[1].split():
            sent = match[2]
    if sent is None or client.select(sent, readonly=True)[0] != "OK":
        raise RuntimeError("Sent folder unavailable")
    status, ids = client.uid("search", None, "HEADER", "Message-ID", '"' + MESSAGE_ID + '"')
    if status != "OK" or len(ids[0].split()) != 1:
        raise RuntimeError("The exact report was not uniquely identified")
    status, values = client.uid("fetch", ids[0].split()[0], "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError("The exact report could not be read")
    message = email.message_from_bytes(b"".join(v[1] for v in values if isinstance(v, tuple)), policy=default)
parts = [part for part in message.walk() if part.get_content_type() == "text/html"]
if len(parts) != 1:
    raise RuntimeError("The report HTML is not unique")
html = parts[0].get_payload(decode=True).decode("utf-8").replace("\r\n", "\n")
import hashlib
if hashlib.sha256(html.encode("utf-8")).hexdigest() != "758ca84b24550a907515a70afa558bd27eb5d98962ce4de14c64c49f816405bb":
    raise RuntimeError("The original report body hash differs")
doc = BeautifulSoup(html, "html5lib")
matches = []
for table in doc.select("table.data-table"):
    headers = [cell.get_text(strip=True) for cell in table.select("thead th")]
    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if any(cell.get_text(strip=True) == "SOXX" for cell in cells):
            matches.append({"table": table.get("id"), "headers": headers,
                            "cells": [{"text": cell.get_text(strip=True),
                                       "titles": [node.get("title") for node in [cell, *cell.select("[title]")] if node.get("title")]}
                                      for cell in cells]})
if not matches:
    raise RuntimeError("SOXX is missing from the exact original report")
print("SOXX_ACTUAL_SENT_ROWS:" + json.dumps({
    "message_id": MESSAGE_ID, "body_sha256_matches": True,
    "subject": str(make_header(decode_header(message.get("Subject", "")))),
    "matches": matches
}, ensure_ascii=False), flush=True)
