#!/usr/bin/env python3
"""Stub for inbound email: POSTs a Postmark-style payload with attachments to a client's inbox webhook.

  python scripts/send_test_email.py --token lpfreight file1.pdf photo.jpg
The token is the client's inbound_email_token (shown on the Clients page; seed clients: lpfreight, gulfcoast).
"""
import argparse
import base64
import json
import mimetypes
import os
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--token", required=True)
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--secret", default=os.environ.get("INBOUND_EMAIL_SECRET", "local-inbound-secret"))
ap.add_argument("files", nargs="+")
a = ap.parse_args()

atts = [{"Name": Path(f).name, "ContentType": mimetypes.guess_type(f)[0] or "application/octet-stream",
         "Content": base64.b64encode(Path(f).read_bytes()).decode()} for f in a.files]
body = json.dumps({"From": "service@shop.example.com", "Subject": "Invoices", "Attachments": atts}).encode()
req = urllib.request.Request(f"{a.api}/inbound/email/{a.token}", data=body, headers={"Content-Type": "application/json", "X-Inbound-Secret": a.secret})
print(urllib.request.urlopen(req).read().decode())
