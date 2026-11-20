import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.orm import Session

from .. import audit, storage
from ..deps import client_db
from ..models import FieldConfidence, Flag, Invoice, InvoiceLine, ReviewStatus, Shop, Upload, UploadStatus, User, Vehicle, VmrsCache
from ..flags.engine import refresh_after_edit
from ..services import normalize as N
from ..services.checks import FAILED_CHECK_PHRASES
from ..services.pipeline import page_key
from .flags import admin_only

router = APIRouter(prefix="/clients/{client_id}/invoices", tags=["invoices"])

HEADER_EDITABLE = {"shop_name", "shop_address", "invoice_number", "invoice_date", "unit_number", "vin", "odometer", "subtotal", "tax", "total"}
LINE_EDITABLE = {"description", "part_number", "qty", "parts_price", "labour_hours", "labour_rate", "line_total", "vmrs_code"}
MONEY = {"subtotal", "tax", "total", "parts_price", "labour_rate", "line_total"}


def _j(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "quantize"):
        return float(v)
    return v


def _conf_map(db: Session, ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, str], FieldConfidence]:
    if not ids:
        return {}
    rows = db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids))).all()
    return {(r.record_id, r.field): r for r in rows}


def _field(value, fc: FieldConfidence | None) -> dict:
    return {
        "value": _j(value),
        "confidence": fc.score if fc else None,
        "needs_review": bool(fc and fc.needs_review),
        "note": fc.note if fc and fc.needs_review else None,
        "corrected": bool(fc and fc.corrected_at),
    }


@router.get("")
def list_invoices(client_id: uuid.UUID, status: str | None = None, db: Session = Depends(client_db)):
    review_counts = dict(
        db.execute(
            select(FieldConfidence.record_id, func.count()).where(FieldConfidence.needs_review.is_(True)).group_by(FieldConfidence.record_id)
        ).all()
    )
    line_to_invoice = dict(db.execute(select(InvoiceLine.id, InvoiceLine.invoice_id)).all())
    per_invoice: dict[uuid.UUID, int] = {}
    for rid, n in review_counts.items():
        inv_id = line_to_invoice.get(rid, rid)
        per_invoice[inv_id] = per_invoice.get(inv_id, 0) + n
    # Newest created first. Invoices created at the same instant (one upload can hold several) keep a stable order, so the list never reshuffles between reloads.
    q = select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(1000)
    if status:
        try:
            q = q.where(Invoice.review_status == ReviewStatus(status))
        except ValueError:
            raise HTTPException(422, "Unknown status. Use needs_review, ready or reviewed.")
    rows = db.scalars(q).all()
    return [
        {
            "id": str(i.id), "shop": i.shop_name_raw, "invoice_number": i.invoice_number, "invoice_date": _j(i.invoice_date),
            "unit_number": i.unit_number, "total": _j(i.total), "review_status": i.review_status.value,
            "fields_to_check": per_invoice.get(i.id, 0) if i.review_status == ReviewStatus.needs_review else 0,
            "created_at": i.created_at.isoformat(),
        }
        for i in rows
    ]


@router.get("/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    up = db.get(Upload, inv.source_upload_id) if inv.source_upload_id else None
    ids = [inv.id] + [ln.id for ln in inv.lines]
    conf = _conf_map(db, ids)
    audit.record(db, action="view", object_type="invoice", object_id=inv.id, request=request)
    return {
        "id": str(inv.id),
        "review_status": inv.review_status.value,
        "source_filename": up.filename if up else None,
        "pages": [{"n": n, "url": f"/clients/{client_id}/invoices/{inv.id}/pages/{n}"} for n in range(inv.page_start, inv.page_end + 1)],
        "header": {f: _field(getattr(inv, "shop_name_raw" if f == "shop_name" else f), conf.get((inv.id, f))) for f in sorted(HEADER_EDITABLE)},
        "lines": [
            {"id": str(ln.id), "line_no": ln.line_no, **{f: _field(getattr(ln, f), conf.get((ln.id, f))) for f in sorted(LINE_EDITABLE)}}
            for ln in inv.lines
        ],
    }


@router.get("/{invoice_id}/pages/{page}")
def get_page(invoice_id: uuid.UUID, page: int, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None or not (inv.page_start <= page <= inv.page_end) or inv.source_upload_id is None:
        raise HTTPException(404, "Page not found.")
    try:
        data = storage.get(page_key(client_id, inv.source_upload_id, page))
    except Exception:
        raise HTTPException(404, "The original file was deleted under the data-retention policy.")
    audit.record(db, action="view", object_type="invoice_page", object_id=inv.id, detail={"page": page}, request=request)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


class FieldEdit(BaseModel):
    field: str
    value: str | None
    line_id: uuid.UUID | None = None


FIELD_LIMITS = {"unit_number": 50, "invoice_number": 80}   # the database column sizes; a longer value used to fail with a 500


def _coerce(field: str, value: str | None):
    if value is None or value.strip() == "":
        return None
    if field in MONEY:
        v = N.parse_money(value)
    elif field == "invoice_date":
        v = N.parse_date(value)
    elif field == "odometer":
        v = N.parse_odometer(value)
    elif field in ("qty", "labour_hours"):
        v = N.parse_number(value)
    elif field == "vin":
        v, _ = N.normalize_vin(value)
    else:
        v = N.clean_text(value, 1000)
    if v is None:
        raise HTTPException(422, f"'{value}' isn't a valid value for {field.replace('_', ' ')}. Enter it the way it appears, for example 1,250.00 or 03/14/2026.")
    if isinstance(v, str) and field in FIELD_LIMITS and len(v) > FIELD_LIMITS[field]:
        raise HTTPException(422, f"That {field.replace('_', ' ')} is too long (the limit is {FIELD_LIMITS[field]} characters). Enter just the number or code as printed.")
    return v


@router.patch("/{invoice_id}/fields")
def edit_field(invoice_id: uuid.UUID, client_id: uuid.UUID, body: FieldEdit, request: Request, db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    if body.line_id:
        row = db.get(InvoiceLine, body.line_id)
        if row is None or row.invoice_id != inv.id or body.field not in LINE_EDITABLE:
            raise HTTPException(404, "That line or field wasn't found.")
        rtype, rid = "line", row.id
    else:
        if body.field not in HEADER_EDITABLE:
            raise HTTPException(422, "That field can't be edited.")
        row, rtype, rid = inv, "invoice", inv.id
    value = _coerce(body.field, body.value)
    if body.field == "vmrs_code" and value is not None:
        from ..models import VmrsCode

        if db.get(VmrsCode, value) is None:
            raise HTTPException(422, "That job code isn't in the VMRS list. Pick a code from the list.")
    attr = "shop_name_raw" if body.field == "shop_name" else body.field
    setattr(row, attr, value)
    if body.field == "vmrs_code":
        row.vmrs_source, row.vmrs_confidence = "analyst", 1.0
        if value is not None and row.description:   # the same description on the next invoice gets the analyst's answer, not the guess again
            key = N.normalize_description(row.description)
            cached = db.scalar(select(VmrsCache).where(VmrsCache.norm_description == key))
            if cached is None:
                db.add(VmrsCache(norm_description=key, vmrs_code=value, confidence=1.0, source="analyst"))
            else:
                cached.vmrs_code, cached.confidence, cached.source = value, 1.0, "analyst"
    if body.field == "shop_name" and value:
        norm = N.normalize_shop_name(value)
        shop = db.scalar(select(Shop).where(Shop.normalized_name == norm)) or Shop(name=value, normalized_name=norm)
        db.add(shop)
        db.flush()
        inv.shop_id = shop.id
    if body.field == "unit_number" and value:
        veh = db.scalar(select(Vehicle).where(Vehicle.unit_number == value)) or Vehicle(unit_number=value)
        db.add(veh)
        db.flush()
        inv.vehicle_id = veh.id
    fc = db.scalar(select(FieldConfidence).where(FieldConfidence.record_id == rid, FieldConfidence.field == body.field))
    if fc is None:
        fc = FieldConfidence(record_type=rtype, record_id=rid, field=body.field, score=1.0, needs_review=False)
        db.add(fc)
    fc.score, fc.needs_review, fc.note = 1.0, False, None
    fc.corrected_by, fc.corrected_at = db.info["user_id"], datetime.now(timezone.utc)
    db.commit()
    refresh_after_edit(db, inv.id)   # the flags on this invoice (and ones that point at it) rest on the number that just changed
    audit.record(db, action="edit", object_type="invoice", object_id=inv.id, detail={"field": body.field, "line": bool(body.line_id)}, request=request)
    return {"ok": True}


def _open_fields(db: Session, inv: Invoice) -> int:
    """Fields on this invoice still marked 'Check' (not yet fixed or confirmed one by one)."""
    ids = [inv.id] + [ln.id for ln in inv.lines]
    return db.scalar(select(func.count()).select_from(FieldConfidence).where(FieldConfidence.record_id.in_(ids), FieldConfidence.needs_review.is_(True))) or 0


def _open_field_names(db: Session, inv: Invoice) -> list[str]:
    ids = [inv.id] + [ln.id for ln in inv.lines]
    return sorted({fc.field for fc in db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids), FieldConfidence.needs_review.is_(True)))})


def _confirm_all(db: Session, inv: Invoice, note: str) -> None:
    ids = [inv.id] + [ln.id for ln in inv.lines]
    for fc in db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids), FieldConfidence.needs_review.is_(True))):
        fc.needs_review, fc.note = False, note   # the model's score is kept, so a low score stays visible


def _check(db: Session, inv: Invoice, uid, now) -> None:
    # Fields are never cleared here: each one marked 'Check' must be fixed or confirmed on its own first (see confirm_field).
    inv.review_status = ReviewStatus.reviewed


class FieldConfirm(BaseModel):
    field: str
    line_id: uuid.UUID | None = None


@router.post("/{invoice_id}/fields/confirm")
def confirm_field(invoice_id: uuid.UUID, client_id: uuid.UUID, body: FieldConfirm, request: Request, db: Session = Depends(client_db)):
    """The analyst looked at the image and the value is right as read. The model's score is kept, so a low score stays visible."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    if body.line_id:
        row = db.get(InvoiceLine, body.line_id)
        if row is None or row.invoice_id != inv.id:
            raise HTTPException(404, "That line wasn't found.")
        rid = row.id
    else:
        rid = inv.id
    fc = db.scalar(select(FieldConfidence).where(FieldConfidence.record_id == rid, FieldConfidence.field == body.field))
    if fc is None or not fc.needs_review:
        raise HTTPException(409, "That field isn't waiting for a check.")
    fc.needs_review = False
    fc.note = "Confirmed as read by an analyst."
    db.commit()
    audit.record(db, action="edit", object_type="invoice", object_id=inv.id, detail={"op": "confirm_field", "field": body.field, "line": bool(body.line_id)}, request=request)
    return {"ok": True, "fields_to_check": _open_fields(db, inv)}


def _refresh_uploads(db: Session, upload_ids: set) -> None:
    """An upload that was waiting on review is done once none of its invoices still needs review."""
    db.flush()
    for uid in upload_ids:
        pending = db.scalar(select(func.count()).select_from(Invoice).where(Invoice.source_upload_id == uid, Invoice.review_status == ReviewStatus.needs_review))
        up = db.get(Upload, uid)
        if up and not pending and up.status == UploadStatus.needs_review:
            up.status = UploadStatus.done


def _failed_checks(db: Session, inv: Invoice) -> list[tuple[str, str]]:
    """(field, note) for every field on the invoice whose arithmetic or VIN check failed and that nobody has corrected."""
    ids = [inv.id] + [ln.id for ln in inv.lines]
    rows = db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids), FieldConfidence.needs_review.is_(True)))
    return [(fc.field, fc.note) for fc in rows if fc.note and any(p in fc.note for p in FAILED_CHECK_PHRASES)]


@router.post("/{invoice_id}/mark-checked")
def mark_checked(invoice_id: uuid.UUID, client_id: uuid.UUID, request: Request, confirm_as_printed: bool = False, db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    failed = _failed_checks(db, inv)
    open_fields = _open_field_names(db, inv)
    if open_fields and not confirm_as_printed:
        if failed:
            fields = ", ".join(sorted({f.replace("_", " ") for f, _ in failed}))
            raise HTTPException(409, f"The numbers on this invoice don't add up ({fields}). Correct the highlighted field, or confirm it is exactly as printed.")
        n = len(open_fields)
        raise HTTPException(409, f"{n} field{'s' if n != 1 else ''} still marked Check. Fix {'each' if n != 1 else 'it'} or press Looks right, then mark the invoice as checked.")
    if open_fields:   # the analyst explicitly says every remaining field is exactly as printed: confirmed, not silently cleared
        _confirm_all(db, inv, "Confirmed as printed by an analyst.")
    _check(db, inv, db.info["user_id"], datetime.now(timezone.utc))
    _refresh_uploads(db, {inv.source_upload_id} if inv.source_upload_id else set())
    db.commit()
    detail = {"op": "mark_checked"}
    if open_fields:
        detail.update(confirmed_as_printed=True, fields=open_fields)
    audit.record(db, action="edit", object_type="invoice", object_id=inv.id, detail=detail, request=request)
    return {"ok": True, "review_status": inv.review_status.value}


class BulkIds(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _owned(db: Session, ids: list[uuid.UUID]) -> list[Invoice]:
    """Invoices from the list that belong to this client (the session is client-scoped, so other clients' ids simply don't appear)."""
    return list(db.scalars(select(Invoice).where(Invoice.id.in_(set(ids)))).all())


@router.post("/bulk-check")
def bulk_check(client_id: uuid.UUID, body: BulkIds, request: Request, db: Session = Depends(client_db)):
    """Mark many invoices as checked at once. Only invoices with no field still marked 'Check' can be marked this way;
    the others are left for the analyst to open, so nothing is waved through unseen."""
    invs = _owned(db, body.ids)
    now, uid = datetime.now(timezone.utc), db.info["user_id"]
    pending = [i for i in invs if i.review_status != ReviewStatus.reviewed]
    todo, blocked = [], []
    for inv in pending:
        open_fields = _open_field_names(db, inv)
        if open_fields:   # nothing marked Check is waved through in bulk: fix or confirm it on the invoice itself
            failed = _failed_checks(db, inv)
            reason = failed[0][1].removeprefix("Check this: ") if failed else \
                f"{len(open_fields)} field{'s' if len(open_fields) != 1 else ''} still marked Check."
            blocked.append({"id": str(inv.id), "fields": sorted({f for f, _ in failed}) or open_fields, "reason": reason})
        else:
            todo.append(inv)
    for inv in todo:
        _check(db, inv, uid, now)
    _refresh_uploads(db, {i.source_upload_id for i in todo if i.source_upload_id})
    db.commit()
    audit.record(db, action="edit", object_type="invoice", detail={"op": "bulk_mark_checked", "count": len(todo), "requested": len(body.ids), "blocked": len(blocked)}, request=request)
    out = {"checked": len(todo), "already_checked": len(invs) - len(pending), "skipped": len(set(body.ids)) - len(invs)}
    if blocked:
        out["blocked"] = blocked
    return out


def _delete_invoices(db: Session, invs: list[Invoice]) -> int:
    if not invs:
        return 0
    ids = [i.id for i in invs]
    line_ids = list(db.scalars(select(InvoiceLine.id).where(InvoiceLine.invoice_id.in_(ids))))
    uploads = {i.source_upload_id for i in invs if i.source_upload_id}
    db.execute(sql_delete(FieldConfidence).where(FieldConfidence.record_id.in_(ids + line_ids)))
    db.execute(sql_delete(Flag).where(Flag.invoice_id.in_(ids)))
    db.execute(sql_delete(Flag).where(Flag.related_invoice_id.in_(ids)))      # a flag that points at a deleted invoice as its 'earlier' repair is no longer valid
    db.execute(sql_delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(ids)))
    db.execute(sql_delete(Invoice).where(Invoice.id.in_(ids)))
    _refresh_uploads(db, uploads)
    return len(ids)


@router.post("/bulk-delete")
def bulk_delete(client_id: uuid.UUID, body: BulkIds, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    """Delete invoices with their lines, confirmation marks and flags. Reports already created are frozen snapshots and are not changed."""
    invs = _owned(db, body.ids)
    n = _delete_invoices(db, invs)
    db.commit()
    audit.record(db, action="delete", object_type="invoice", detail={"count": n, "requested": len(body.ids)}, request=request)
    return {"deleted": n, "skipped": len(set(body.ids)) - n}


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: uuid.UUID, client_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    _delete_invoices(db, [inv])
    db.commit()
    audit.record(db, action="delete", object_type="invoice", object_id=invoice_id, detail={"count": 1}, request=request)
