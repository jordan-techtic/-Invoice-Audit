import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, storage
from ..deps import client_db
from ..models import FieldConfidence, Invoice, InvoiceLine, ReviewStatus, Shop, Upload, UploadStatus, Vehicle
from ..services import normalize as N
from ..services.pipeline import page_key

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
    q = select(Invoice).order_by(Invoice.created_at.desc()).limit(1000)
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
    audit.record(db, action="edit", object_type="invoice", object_id=inv.id, detail={"field": body.field, "line": bool(body.line_id)}, request=request)
    return {"ok": True}


@router.post("/{invoice_id}/mark-checked")
def mark_checked(invoice_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found.")
    ids = [inv.id] + [ln.id for ln in inv.lines]
    now, uid = datetime.now(timezone.utc), db.info["user_id"]
    for fc in db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids), FieldConfidence.needs_review.is_(True))):
        fc.needs_review, fc.corrected_by, fc.corrected_at = False, uid, now
    inv.review_status = ReviewStatus.reviewed
    db.flush()
    if inv.source_upload_id:
        pending = db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.source_upload_id == inv.source_upload_id, Invoice.review_status == ReviewStatus.needs_review))
        up = db.get(Upload, inv.source_upload_id)
        if up and not pending and up.status == UploadStatus.needs_review:
            up.status = UploadStatus.done
    db.commit()
    audit.record(db, action="edit", object_type="invoice", object_id=inv.id, detail={"op": "mark_checked"}, request=request)
    return {"ok": True, "review_status": inv.review_status.value}
