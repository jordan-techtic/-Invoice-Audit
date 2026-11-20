"""Analyst review: flag detail, accept / dismiss / edit / reopen, and re-checking one invoice."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..deps import client_db
from ..flags.engine import run_flag_engine
from ..flags.evidence import evidence_lines
from ..models import Flag, FlagStatus, Invoice, InvoiceLine, User
from ..models import User as UserModel

router = APIRouter(prefix="/clients/{client_id}", tags=["review"])

DISMISS_REASONS = {"wrong_extraction", "valid_reason", "not_real_issue", "other"}


def _name(db: Session, uid) -> str | None:
    if not uid:
        return None
    u = db.get(UserModel, uid)
    return u.name if u else None


def _j(v):
    return float(v) if isinstance(v, Decimal) else v


def flag_detail(db: Session, f: Flag, client_id: uuid.UUID) -> dict:
    inv = db.get(Invoice, f.invoice_id)
    ln = db.get(InvoiceLine, f.line_id) if f.line_id else None
    flagged_page = (ln.page_no if ln and ln.page_no else inv.page_start)
    return {
        "id": str(f.id), "type": f.type.value, "severity": f.severity.value, "status": f.status.value,
        "impact": float(f.estimated_dollar_impact), "original_impact": _j(f.original_impact),
        "reason": f.plain_english_reason, "original_reason": f.original_reason, "ai_score": f.ai_score,
        "dismiss_reason": f.dismiss_reason, "note": f.analyst_note,
        "reviewed_by": _name(db, f.reviewed_by), "reviewed_at": f.reviewed_at,
        "evidence_lines": evidence_lines(f.type.value, f.details or {}, f.estimated_dollar_impact),
        "invoice": {
            "id": str(inv.id), "invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "shop": inv.shop_name_raw, "unit": inv.unit_number, "vin": inv.vin, "odometer": inv.odometer, "total": _j(inv.total),
            "pages": [{"n": n, "url": f"/clients/{client_id}/invoices/{inv.id}/pages/{n}"} for n in range(inv.page_start, inv.page_end + 1)],
            "flagged_page": flagged_page,
        },
        "line": {"id": str(ln.id), "line_no": ln.line_no, "description": ln.description, "y_center": ln.y_center} if ln else None,
        "lines": [{"id": str(l.id), "line_no": l.line_no, "description": l.description, "part_number": l.part_number, "qty": _j(l.qty),
                   "parts_price": _j(l.parts_price), "labour_hours": _j(l.labour_hours), "labour_rate": _j(l.labour_rate),
                   "line_total": _j(l.line_total), "flagged": bool(ln and l.id == ln.id)} for l in inv.lines],
    }


def _get(db: Session, fid: uuid.UUID) -> Flag:
    f = db.get(Flag, fid)
    if f is None:
        raise HTTPException(404, "Flag not found.")
    return f


def _doubtful(f: Flag) -> bool:
    """The flag rests on numbers the extraction was unsure about (low stored score) that nobody has corrected."""
    return bool((f.details or {}).get("extraction_uncertain"))


def _stamp(db: Session, f: Flag) -> None:
    f.reviewed_by, f.reviewed_at = db.info["user_id"], datetime.now(timezone.utc)


@router.get("/flags/filters")
def filters(client_id: uuid.UUID, db: Session = Depends(client_db)):
    rows = db.execute(select(Invoice.shop_name_raw, Invoice.unit_number).join(Flag, Flag.invoice_id == Invoice.id)).all()
    return {"shops": sorted({r[0] for r in rows if r[0]}), "units": sorted({r[1] for r in rows if r[1]})}


@router.get("/flags/{flag_id}")
def get_flag(flag_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    f = _get(db, flag_id)
    audit.record(db, action="view", object_type="flag", object_id=f.id, request=request)
    return flag_detail(db, f, client_id)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class DismissIn(NoteIn):
    reason: str


class EditIn(NoteIn):
    amount: float | None = Field(default=None, ge=0, le=10_000_000)
    reason: str | None = Field(default=None, min_length=1, max_length=1000)


class AcceptIn(NoteIn):
    extraction_checked: bool = False   # "I looked at the invoice image and the numbers behind this flag are right"


class BulkIn(NoteIn):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: str
    reason: str | None = None
    extraction_checked: bool = False


@router.post("/flags/bulk")
def bulk(client_id: uuid.UUID, body: BulkIn, request: Request, db: Session = Depends(client_db)):
    """Accept, dismiss or reopen many flags at once. Same rules as the one-flag actions; the session is client-scoped,
    so ids from another client are simply not found and are counted as skipped."""
    if body.action not in {"accept", "dismiss", "reopen"}:
        raise HTTPException(422, "Pick an action: accept, dismiss or reopen.")
    if body.action == "dismiss" and body.reason not in DISMISS_REASONS:
        raise HTTPException(422, "Pick a reason: wrong extraction, shop had a valid reason, not a real issue, or other.")
    flags = list(db.scalars(select(Flag).where(Flag.id.in_(set(body.ids)))).all())
    changed = 0
    needs_check: list[str] = []
    for f in flags:
        if body.action == "accept" and _doubtful(f) and not body.extraction_checked and f.status != FlagStatus.accepted:
            needs_check.append(str(f.id))   # accepting puts it in the client's report: look at the image first
            continue
        if body.action == "reopen":
            if f.status == FlagStatus.open:
                continue
            f.status, f.dismiss_reason, f.reviewed_by, f.reviewed_at = FlagStatus.open, None, None, None
        else:
            target = FlagStatus.accepted if body.action == "accept" else FlagStatus.dismissed
            if f.status == target and (body.action == "accept" or f.dismiss_reason == body.reason):
                continue
            f.status, f.dismiss_reason = target, (body.reason if body.action == "dismiss" else None)
            if body.note is not None:
                f.analyst_note = body.note
            _stamp(db, f)
        changed += 1
    db.commit()
    audit.record(db, action=body.action if body.action != "reopen" else "edit", object_type="flag",
                 detail={"op": f"bulk_{body.action}", "count": changed, "requested": len(body.ids), "reason": body.reason}, request=request)
    out = {"changed": changed, "unchanged": len(flags) - changed - len(needs_check), "skipped": len(set(body.ids)) - len(flags)}
    if needs_check:
        out["needs_extraction_check"] = needs_check
    return out


@router.post("/flags/{flag_id}/accept")
def accept(flag_id: uuid.UUID, client_id: uuid.UUID, body: AcceptIn, request: Request, db: Session = Depends(client_db)):
    f = _get(db, flag_id)
    if _doubtful(f) and not body.extraction_checked and f.status != FlagStatus.accepted:
        raise HTTPException(409, "Some numbers behind this flag were hard to read on the invoice. Check them against the invoice image first: correct a wrong number "
                                 "(the flag refreshes) or confirm they are right, then accept it.")
    f.status, f.dismiss_reason = FlagStatus.accepted, None
    if body.note is not None:
        f.analyst_note = body.note
    _stamp(db, f)
    db.commit()
    audit.record(db, action="accept", object_type="flag", object_id=f.id, detail={"type": f.type.value}, request=request)
    return flag_detail(db, f, client_id)


@router.post("/flags/{flag_id}/dismiss")
def dismiss(flag_id: uuid.UUID, client_id: uuid.UUID, body: DismissIn, request: Request, db: Session = Depends(client_db)):
    if body.reason not in DISMISS_REASONS:
        raise HTTPException(422, "Pick a reason: wrong extraction, shop had a valid reason, not a real issue, or other.")
    f = _get(db, flag_id)
    f.status, f.dismiss_reason = FlagStatus.dismissed, body.reason
    if body.note is not None:
        f.analyst_note = body.note
    _stamp(db, f)
    db.commit()
    audit.record(db, action="dismiss", object_type="flag", object_id=f.id, detail={"type": f.type.value, "reason": body.reason}, request=request)
    return flag_detail(db, f, client_id)


@router.post("/flags/{flag_id}/edit")
def edit(flag_id: uuid.UUID, client_id: uuid.UUID, body: EditIn, request: Request, db: Session = Depends(client_db)):
    f = _get(db, flag_id)
    if body.amount is None and body.reason is None and body.note is None:
        raise HTTPException(422, "Change the amount, the reason or the note, then save.")
    changed = []
    if body.amount is not None:
        if f.original_impact is None:
            f.original_impact = f.estimated_dollar_impact
        f.estimated_dollar_impact = Decimal(str(body.amount)).quantize(Decimal("0.01"))
        changed.append("amount")
    if body.reason is not None:
        if f.original_reason is None:
            f.original_reason = f.plain_english_reason
        f.plain_english_reason = body.reason.strip()
        changed.append("reason")
    if body.note is not None:
        f.analyst_note = body.note
        changed.append("note")
    f.status, f.dismiss_reason = FlagStatus.edited, None  # an edited flag is a confirmed flag
    _stamp(db, f)
    db.commit()
    audit.record(db, action="edit", object_type="flag", object_id=f.id, detail={"fields": changed}, request=request)
    return flag_detail(db, f, client_id)


@router.post("/flags/{flag_id}/reopen")
def reopen(flag_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    f = _get(db, flag_id)
    f.status, f.dismiss_reason, f.reviewed_by, f.reviewed_at = FlagStatus.open, None, None, None
    db.commit()
    audit.record(db, action="edit", object_type="flag", object_id=f.id, detail={"op": "reopen"}, request=request)
    return flag_detail(db, f, client_id)


@router.post("/invoices/{invoice_id}/recheck")
def recheck(invoice_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    if db.get(Invoice, invoice_id) is None:
        raise HTTPException(404, "Invoice not found.")
    s = run_flag_engine(db, only_invoice=str(invoice_id))
    db.commit()
    audit.record(db, action="edit", object_type="invoice", object_id=invoice_id, detail={"op": "recheck", "added": s["added"], "removed": s["removed"]}, request=request)
    return {"flags": s["flags"], "added": s["added"], "removed": s["removed"]}
