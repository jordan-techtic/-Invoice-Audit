"""Inbound email webhook (Postmark-style JSON; SES via SNS can be adapted to the same shape).

POST /inbound/email/{token}   header X-Inbound-Secret: <secret>
Body: {"From": "...", "Subject": "...", "Attachments": [{"Name","ContentType","Content"(base64)}]}
The token identifies the client (each client has its own address, e.g. <token>@in.example.com).
Attachment bytes are validated by magic number, not by the declared type.
"""

import base64
import binascii
import hmac

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..db import bind_client, system_session, SessionLocal
from ..models import Client, UploadSource
from ..services.ingest import RejectedFile, ingest_file
from .uploads import upload_out

router = APIRouter(prefix="/inbound", tags=["inbound"])


@router.post("/email/{token}")
def inbound_email(token: str, payload: dict, x_inbound_secret: str = Header(default="")):
    if not hmac.compare_digest(x_inbound_secret, get_settings().inbound_email_secret):
        raise HTTPException(401, "Invalid inbound secret.")
    with system_session() as sysdb:
        client_id = sysdb.scalar(select(Client.id).where(Client.inbound_email_token == token))
    if client_id is None:
        raise HTTPException(404, "Unknown inbox.")
    db = SessionLocal()
    bind_client(db, client_id)
    db.info["user_id"] = None
    out = []
    try:
        for att in payload.get("Attachments", []) or []:
            try:
                data = base64.b64decode(att.get("Content", ""), validate=False)
            except (binascii.Error, ValueError):
                out.append({"ok": False, "filename": att.get("Name"), "error": "Attachment could not be decoded."})
                continue
            try:
                up = ingest_file(db, filename=att.get("Name") or "attachment", data=data, source=UploadSource.email)
                out.append({"ok": True, "upload": upload_out(up)})
            except RejectedFile as e:
                out.append({"ok": False, "filename": att.get("Name"), "error": str(e)})
    finally:
        db.close()
    return {"received": len(out), "results": out}
