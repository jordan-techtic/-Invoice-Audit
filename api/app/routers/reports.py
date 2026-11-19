"""Client reports: create (accepted flags only), list, open, PDF, revoke, and the public read-only link."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, storage
from ..config import get_settings
from ..db import bind_client, system_session, SessionLocal
from ..deps import client_db, current_user
from ..models import Client, Report, Role, User
from ..security import decrypt_bytes, encrypt_bytes, new_token, sha256_hex
from ..services import report_data
from ..services.report_pdf import render_pdf
from .flags import admin_only

router = APIRouter(tags=["reports"])


class ReportIn(BaseModel):
    expires_days: int | None = Field(default=None, ge=1, le=365)
    offer_text: str | None = Field(default=None, max_length=5000)


def _pdf_key(client_id, report_id) -> str:
    return f"reports/{client_id}/{report_id}.pdf"  # outside clients/<id>/ so deleting raw files keeps reports


def _item(r: Report) -> dict:
    now = datetime.now(timezone.utc)
    revoked = r.revoked_at is not None
    expired = bool(r.share_expires_at and r.share_expires_at < now)
    url = None
    if r.share_token_enc and not revoked:
        url = f"{get_settings().public_base_url}/r/{decrypt_bytes(r.share_token_enc).decode()}"
    return {"id": str(r.id), "version": r.version, "generated_at": r.generated_at, "recoverable": float(r.recoverable), "flag_count": r.flag_count,
            "expires_at": r.share_expires_at, "revoked": revoked, "expired": expired, "share_url": url}


def _snapshot(r: Report) -> dict:
    return {**r.snapshot, "id": str(r.id), "version": r.version}


@router.get("/clients/{client_id}/report-settings")
def report_settings(client_id: uuid.UUID, db: Session = Depends(client_db)):
    cfg = report_data.load_settings()
    return {"default_offer_text": cfg["default_offer_text"], "company_name": cfg["company_name"], "default_expiry_days": cfg["link_expiry_days_default"]}


@router.post("/clients/{client_id}/reports", status_code=201)
def create_report(client_id: uuid.UUID, body: ReportIn, request: Request, db: Session = Depends(client_db)):
    n_open = report_data.open_flag_count(db)
    if n_open:
        raise HTTPException(409, f"{n_open} {'flag still needs' if n_open == 1 else 'flags still need'} a decision. Accept or dismiss {'it' if n_open == 1 else 'them'} first, then create the report.")
    if not report_data.has_run_checks(db):
        raise HTTPException(409, "No checks have been run yet. Run checks on the invoices first, then review the flags.")
    client = db.get(Client, client_id)
    days = body.expires_days or report_data.load_settings()["link_expiry_days_default"]
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    try:
        from ..services.extraction import get_provider

        provider = get_provider()
    except Exception:  # noqa: BLE001  (no key / AI off): the report still builds with standard wording
        provider = None
    snap = report_data.build_snapshot(db, client, body.offer_text, provider, expires)
    version = (db.scalar(select(func.max(Report.version))) or 0) + 1
    token = new_token(32)
    rep = Report(generated_at=datetime.now(timezone.utc), generated_by=db.info["user_id"], version=version, summary=snap["summary"], snapshot=snap,
                 recoverable=snap["summary"]["recoverable"], flag_count=snap["summary"]["flag_count"], share_token_hash=sha256_hex(token),
                 share_token_enc=encrypt_bytes(token.encode()), share_expires_at=expires)
    db.add(rep)
    db.flush()
    pdf = render_pdf(_snapshot(rep))
    rep.file_path = _pdf_key(client_id, rep.id)
    storage.put(rep.file_path, pdf, "application/pdf")
    db.commit()
    audit.record(db, action="create", object_type="report", object_id=rep.id, detail={"version": version, "flags": rep.flag_count}, request=request)
    return _item(rep)


@router.get("/clients/{client_id}/reports")
def list_reports(client_id: uuid.UUID, db: Session = Depends(client_db)):
    return [_item(r) for r in db.scalars(select(Report).order_by(Report.version.desc()))]


def _get(db: Session, rid: uuid.UUID) -> Report:
    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "Report not found.")
    return r


@router.get("/clients/{client_id}/reports/{report_id}")
def get_report(client_id: uuid.UUID, report_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    r = _get(db, report_id)
    audit.record(db, action="view", object_type="report", object_id=r.id, request=request)
    return _snapshot(r)


def _pdf_response(r: Report) -> Response:
    try:
        data = storage.get(r.file_path)
    except Exception:  # noqa: BLE001
        data = render_pdf(_snapshot(r))
    name = f"repair-invoice-audit-v{r.version}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@router.get("/clients/{client_id}/reports/{report_id}/pdf")
def report_pdf(client_id: uuid.UUID, report_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    r = _get(db, report_id)
    audit.record(db, action="export", object_type="report", object_id=r.id, detail={"format": "pdf"}, request=request)
    return _pdf_response(r)


@router.post("/clients/{client_id}/reports/{report_id}/revoke")
def revoke(client_id: uuid.UUID, report_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    r = _get(db, report_id)
    r.revoked_at = datetime.now(timezone.utc)
    db.commit()
    audit.record(db, action="edit", object_type="report", object_id=r.id, detail={"op": "revoke_link"}, request=request)
    return _item(r)


# ---------------------------------------------------------------- public, read-only link (no login)


def _public(token: str) -> tuple[Report, SessionLocal]:
    """Resolve a share token. 404 if unknown, 410 if expired or revoked. Returns (report, open session) bound to its client."""
    with system_session() as sysdb:
        row = sysdb.execute(select(Report.id, Report.client_id).where(Report.share_token_hash == sha256_hex(token))).first()
    if row is None:
        raise HTTPException(404, "This link isn't valid. Check that you copied the whole link.")
    db = SessionLocal()
    bind_client(db, row.client_id)
    r = db.get(Report, row.id)
    if r.revoked_at is not None:
        db.close()
        raise HTTPException(410, "This link has been turned off. Ask your Techtic contact for a new one.")
    if r.share_expires_at and r.share_expires_at < datetime.now(timezone.utc):
        db.close()
        raise HTTPException(410, "This link has expired. Ask your Techtic contact for a new one.")
    return r, db


@router.get("/public/reports/{token}")
def public_report(token: str, request: Request):
    r, db = _public(token)
    try:
        audit.record(db, action="view", object_type="report", object_id=r.id, detail={"via": "public_link"}, request=request, client_id=r.client_id)
        return _snapshot(r)
    finally:
        db.close()


@router.get("/public/reports/{token}/pdf")
def public_pdf(token: str, request: Request):
    r, db = _public(token)
    try:
        audit.record(db, action="export", object_type="report", object_id=r.id, detail={"via": "public_link", "format": "pdf"}, request=request, client_id=r.client_id)
        return _pdf_response(r)
    finally:
        db.close()
