"""Upload -> pages -> AI extraction -> split -> normalise/check -> invoices, lines, field confidence, VMRS."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..db import client_session
from ..models import (
    Client,
    ExtractionRun,
    FieldConfidence,
    Invoice,
    InvoiceLine,
    ReviewStatus,
    Shop,
    Upload,
    UploadStatus,
    Vehicle,
)
from ..security import encrypt_bytes
from . import vmrs
from .checks import FieldResult, normalise_and_check
from .extraction import ExtractionError, get_provider
from .extraction.base import ExtractionProvider
from .extraction.schema import PageExtraction
from .normalize import normalize_shop_name
from .preprocess import UnreadableFile, prepare_page, render_pages, sniff_type
from .splitter import merge_group, split_pages

log = logging.getLogger("audit.pipeline")  # never log invoice contents


def page_key(client_id: uuid.UUID, upload_id: uuid.UUID, n: int) -> str:
    return f"{storage.client_prefix(client_id)}{upload_id}/pages/{n}.jpg"


def _record_run(db: Session, upload: Upload, provider: ExtractionProvider, out, purpose: str) -> None:
    s = get_settings()
    usage = out.usage
    cost = (usage.input_tokens * s.price_input_per_mtok + usage.output_tokens * s.price_output_per_mtok) / 1_000_000
    db.add(
        ExtractionRun(
            upload_id=upload.id,
            provider=provider.name,
            model=provider.model,
            purpose=purpose,
            attempts=out.attempts,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=Decimal(str(round(cost, 5))),
            duration_ms=usage.duration_ms,
            raw_response_encrypted=encrypt_bytes(json.dumps(out.raw_responses).encode()),
        )
    )


def _purge_previous(db: Session, upload: Upload) -> None:
    ids = list(db.scalars(select(Invoice.id).where(Invoice.source_upload_id == upload.id)))
    if ids:
        line_ids = list(db.scalars(select(InvoiceLine.id).where(InvoiceLine.invoice_id.in_(ids))))
        db.execute(delete(FieldConfidence).where(FieldConfidence.record_id.in_(ids + line_ids)))
        db.execute(delete(Invoice).where(Invoice.id.in_(ids)))
    db.execute(delete(ExtractionRun).where(ExtractionRun.upload_id == upload.id))
    db.flush()


def _fail(db: Session, upload: Upload, message: str) -> None:
    db.rollback()
    up = db.get(Upload, upload.id)
    up.status = UploadStatus.failed
    up.status_detail = message
    db.commit()


def process_upload(client_id: str, upload_id: str) -> None:
    cid, uid = uuid.UUID(client_id), uuid.UUID(upload_id)
    with client_session(cid) as db:
        up = db.get(Upload, uid)
        if up is None or up.status == UploadStatus.duplicate:
            return
        up.status, up.status_detail = UploadStatus.reading, None
        _purge_previous(db, up)
        db.commit()
        try:
            _run(db, cid, up)
        except (ExtractionError, UnreadableFile) as e:
            _fail(db, up, str(e))
        except Exception as e:  # noqa: BLE001
            log.error("upload %s failed: %s", upload_id, type(e).__name__)
            _fail(db, up, "Something went wrong while reading this file. Retry it; if it fails again, send us the file name.")


def _run(db: Session, cid: uuid.UUID, up: Upload) -> None:
    s = get_settings()
    client = db.get(Client, cid)
    threshold = float(client.settings.get("confidence_threshold", s.confidence_threshold))
    tolerance = Decimal(str(client.settings.get("math_tolerance", 1.0)))

    data = storage.get(up.storage_key)
    kind = sniff_type(data)
    images = render_pages(data, kind, s.max_pdf_pages)
    provider = get_provider()

    pages: list[PageExtraction] = []
    for n, img in enumerate(images, start=1):
        jpg = prepare_page(img)
        res = provider.extract_page(jpg)
        _record_run(db, up, provider, res, "extraction")
        if res.page.is_invoice and res.page.rotation_degrees in (90, 180, 270):
            jpg = prepare_page(img, rotate_cw=res.page.rotation_degrees)  # the AI says it is sideways/upside down
            res = provider.extract_page(jpg)
            _record_run(db, up, provider, res, "extraction")
        pages.append(res.page)
        storage.put(page_key(cid, up.id, n), jpg, "image/jpeg")
    up.page_count = len(images)
    db.commit()

    groups = split_pages(pages)
    if not groups:
        raise ExtractionError("We couldn't find an invoice in this file. Check that it shows a repair invoice and upload it again.")

    any_review = False
    for idxs in groups:
        merged = merge_group(pages, idxs)
        result = normalise_and_check(merged.header, merged.lines, tolerance=tolerance, threshold=threshold)
        inv = _store_invoice(db, up, merged, result, threshold, provider)
        any_review = any_review or inv.review_status == ReviewStatus.needs_review
    up.invoice_count = len(groups)
    up.status = UploadStatus.needs_review if any_review else UploadStatus.done
    up.status_detail = None
    db.commit()


def _fc(db: Session, rtype: str, rid: uuid.UUID, field: str, fr: FieldResult, threshold: float) -> bool:
    review = fr.failed_check or (fr.value not in (None, "") and fr.confidence < threshold)
    db.add(FieldConfidence(record_type=rtype, record_id=rid, field=field, score=fr.confidence, needs_review=review, note=fr.note if review else None))
    return review


def _store_invoice(db, up: Upload, merged, result, threshold: float, provider) -> Invoice:
    h = result.header
    shop = None
    if h["shop_name"].value:
        norm = normalize_shop_name(h["shop_name"].value)
        shop = db.scalar(select(Shop).where(Shop.normalized_name == norm))
        if not shop:
            shop = Shop(name=h["shop_name"].value, normalized_name=norm)
            db.add(shop)
            db.flush()
    vehicle = None
    if h["unit_number"].value:
        vehicle = db.scalar(select(Vehicle).where(Vehicle.unit_number == h["unit_number"].value))
        if not vehicle:
            vehicle = Vehicle(unit_number=h["unit_number"].value, vin=h["vin"].value if h["vin"].value and len(h["vin"].value) == 17 else None)
            db.add(vehicle)
            db.flush()
        elif not vehicle.vin and h["vin"].value and len(h["vin"].value) == 17:
            vehicle.vin = h["vin"].value

    inv = Invoice(
        shop_id=shop.id if shop else None,
        vehicle_id=vehicle.id if vehicle else None,
        source_upload_id=up.id,
        page_start=merged.page_start,
        page_end=merged.page_end,
        shop_name_raw=h["shop_name"].value,
        shop_address=h["shop_address"].value,
        invoice_number=h["invoice_number"].value,
        invoice_date=h["invoice_date"].value,
        unit_number=h["unit_number"].value,
        vin=h["vin"].value,
        odometer=h["odometer"].value,
        subtotal=h["subtotal"].value,
        tax=h["tax"].value,
        total=h["total"].value,
    )
    db.add(inv)
    db.flush()

    review = False
    for k, f in h.items():
        review |= _fc(db, "invoice", inv.id, k, f, threshold)

    descs = [str(ln["description"].value or "") for ln in result.lines]
    classes = vmrs.classify_lines(db, descs, provider, record_run=lambda out, purpose: _record_run(db, up, provider, out, purpose))
    for n, (ln, cls) in enumerate(zip(result.lines, classes), start=1):
        row = InvoiceLine(
            invoice_id=inv.id,
            line_no=n,
            description=ln["description"].value or "",
            part_number=ln["part_number"].value,
            qty=ln["qty"].value,
            parts_price=ln["parts_price"].value,
            labour_hours=ln["labour_hours"].value,
            labour_rate=ln["labour_rate"].value,
            line_total=ln["line_total"].value,
            vmrs_code=cls.code,
            vmrs_confidence=cls.confidence,
            vmrs_source=cls.source,
        )
        db.add(row)
        db.flush()
        for k, f in ln.items():
            if f.value not in (None, "") or f.failed_check:
                review |= _fc(db, "line", row.id, k, f, threshold)
        vf = FieldResult(cls.code, cls.confidence, "Check this: job type is a best guess." if cls.confidence < threshold or not cls.code else None)
        db.add(FieldConfidence(record_type="line", record_id=row.id, field="vmrs_code", score=cls.confidence,
                               needs_review=cls.code is None or cls.confidence < threshold, note=vf.note))
        review |= cls.code is None or cls.confidence < threshold
    inv.review_status = ReviewStatus.needs_review if review else ReviewStatus.ready
    db.flush()
    return inv


def retry_upload(db: Session, upload: Upload) -> None:
    from ..queue import enqueue

    upload.status, upload.status_detail = UploadStatus.queued, None
    db.commit()
    enqueue("extraction", "app.jobs.process_upload", str(upload.client_id), str(upload.id))
