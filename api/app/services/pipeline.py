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
from . import crosschecks, normalize, vmrs
from .checks import FieldResult, _lower, normalise_and_check
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
    disagreements: list[dict] = []
    for n, img in enumerate(images, start=1):
        jpg = prepare_page(img)
        res = provider.extract_page(jpg)
        _record_run(db, up, provider, res, "extraction")
        if res.page.is_invoice and res.page.rotation_degrees in (90, 180, 270):
            jpg = prepare_page(img, rotate_cw=res.page.rotation_degrees)  # the AI says it is sideways/upside down
            res = provider.extract_page(jpg)
            _record_run(db, up, provider, res, "extraction")
        page, differ = res.page, {}
        problems = page_problems(page, tolerance) if page.is_invoice and provider.second_read else []
        if problems:  # the numbers on this page don't add up: read it once more, pointing at where, and compare the two readings
            again = provider.extract_page(jpg, hint=second_read_hint(problems))
            _record_run(db, up, provider, again, "extraction_second_read")
            page, differ = reconcile(page, again.page, tolerance)
        pages.append(page)
        disagreements.append(differ)
        storage.put(page_key(cid, up.id, n), jpg, "image/jpeg")
    up.page_count = len(images)
    db.commit()

    groups = split_pages(pages)
    if not groups:
        raise ExtractionError("We couldn't find an invoice in this file. Check that it shows a repair invoice and upload it again.")

    any_review = False
    stored, copies = 0, []
    for idxs in groups:
        merged = merge_group(pages, idxs)
        apply_disagreements(merged, idxs, pages, disagreements)
        result = normalise_and_check(merged.header, merged.lines, tolerance=tolerance, threshold=threshold)
        same = same_invoice_already_stored(db, up, result.header)
        if same is not None:  # a second photo or scan of an invoice we already have: de-duplicate, never a flag
            copies.append(same)
            continue
        fleet_checks(db, result.header)
        inv = _store_invoice(db, up, merged, result, threshold, provider)
        stored += 1
        any_review = any_review or inv.review_status == ReviewStatus.needs_review
    up.invoice_count = stored
    up.status_detail = None
    if copies and not stored:
        first = copies[0]
        src = db.get(Upload, first.source_upload_id) if first.source_upload_id else None
        up.status, up.duplicate_of = UploadStatus.duplicate, (src.id if src else None)
        up.status_detail = (f"Skipped: the same invoice{f' ({first.invoice_number})' if first.invoice_number else ''} is already in"
                            f"{f' {src.filename}' if src else ' this audit'}. It looks like another photo or scan of the same paper.")
    else:
        up.status = UploadStatus.needs_review if any_review else UploadStatus.done
        if copies:
            up.status_detail = f"{len(copies)} invoice{'s' if len(copies) != 1 else ''} in this file {'were' if len(copies) != 1 else 'was'} already uploaded, so {'they were' if len(copies) != 1 else 'it was'} skipped."
    db.commit()


# ------------------------------------------------------------------ second read (fix-list X5)
NUMERIC_LINE = ("qty", "parts_price", "labour_hours", "labour_rate", "line_total")
COMPARED_HEADER = ("invoice_number", "invoice_date", "unit_number", "vin", "odometer", "subtotal", "tax", "total")
DIFFER_NOTE = "Check this: two readings of this number disagree, so one of them is probably a misread."


def _num(v) -> Decimal | None:
    return normalize.parse_money(v) if v is not None else None


def page_problems(page: PageExtraction, tol: Decimal) -> list[str]:
    """Where the numbers on one page don't add up, in words the model can act on. Empty when everything adds up."""
    out: list[str] = []
    for n, ln in enumerate(page.lines, start=1):
        tot, price, qty = _num(ln.line_total.value), _num(ln.parts_price.value), _num(ln.qty.value)
        hrs, rate = _num(ln.labour_hours.value), _num(ln.labour_rate.value)
        if tot is None:
            continue
        lab = hrs * rate if hrs is not None and rate is not None else None
        if price is None and lab is None:
            continue
        q = qty if qty and qty > 0 else Decimal(1)
        cands = {q * price + (lab or 0), price + (lab or 0)} if price is not None else {lab}
        name = str(ln.description.value or "")[:40]
        if all(abs(c - tot) > tol for c in cands):
            out.append(f"line {n} ({name}): quantity {qty}, price {price}, hours {hrs} and rate {rate} don't give its total {tot}")
        elif price is not None and q > 1 and not lab and abs(price - tot) <= tol:
            out.append(f"line {n} ({name}): the price for one equals the line total although the quantity is {q}")
    totals = [_num(ln.line_total.value) for ln in page.lines]
    total, tax = _num(page.header.total.value), _num(page.header.tax.value)
    if total is not None and totals and all(t is not None for t in totals) and abs(sum(totals) + (tax or 0) - total) > tol:
        out.append(f"the line totals ({sum(totals)}) plus tax ({tax}) don't equal the total ({total})")
    return out


def second_read_hint(problems: list[str]) -> str:
    return ("A first reading of this page did not add up here:\n- " + "\n- ".join(problems) +
            "\nRead every number on the page again, digit by digit, exactly as it is printed. If the shop's own arithmetic is wrong, "
            "copy it as printed anyway: never correct it.")


def _same(a, b) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    return _alnum(a) == _alnum(b)


def reconcile(first: PageExtraction, second: PageExtraction, tol: Decimal) -> tuple[PageExtraction, dict]:
    """Keep the reading whose numbers add up better, and list every number the two readings disagree on so a person looks at it.
    When the second reading is not usable (different number of lines, or not an invoice) the first is kept as it was."""
    if not second.is_invoice or len(second.lines) != len(first.lines):
        return first, {}
    keep = second if len(page_problems(second, tol)) < len(page_problems(first, tol)) else first
    differ: dict = {"header": set(), "lines": {}}
    for f in COMPARED_HEADER:
        if not _same(getattr(first.header, f).value, getattr(second.header, f).value):
            differ["header"].add(f)
    for j, (a, b) in enumerate(zip(first.lines, second.lines)):
        bad = {f for f in NUMERIC_LINE if not _same(getattr(a, f).value, getattr(b, f).value)}
        if bad:
            differ["lines"][j] = bad
    return keep, differ


def apply_disagreements(merged, idxs: list[int], pages: list[PageExtraction], disagreements: list[dict]) -> None:
    """Carry each page's "the readings disagree" marks onto the merged invoice: lower the field and say why."""
    def mark(d: dict) -> None:
        d["confidence"] = min(float(d["confidence"]), 0.5)
        d["note"] = DIFFER_NOTE
    for i in idxs:
        for f in disagreements[i].get("header", ()):
            if merged.header.get(f, {}).get("value") is not None:
                mark(merged.header[f])
    k = 0
    for i in idxs:
        for j in range(len(pages[i].lines)):
            for f in disagreements[i].get("lines", {}).get(j, ()):
                if merged.lines[k].get(f, {}).get("value") is not None:
                    mark(merged.lines[k][f])
            k += 1


def _alnum(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


def same_invoice_already_stored(db: Session, up: Upload, h: dict[str, FieldResult]) -> Invoice | None:
    """An invoice from another file with the same shop, invoice number, date and total is the same piece of paper uploaded
    twice (for example a phone photo of a scanned invoice). Billing the same job again shows up as a new number or date,
    which the duplicate rule checks instead."""
    num, d, total, shop = h["invoice_number"].value, h["invoice_date"].value, h["total"].value, h["shop_name"].value
    if not (num and d and total is not None and shop):
        return None
    for inv in db.scalars(select(Invoice).where(Invoice.invoice_date == d, Invoice.total == total)):
        if inv.source_upload_id != up.id and _alnum(inv.invoice_number) == _alnum(num) and \
                normalize_shop_name(inv.shop_name_raw or "") == normalize_shop_name(shop):
            return inv
    return None


def fleet_checks(db: Session, h: dict[str, FieldResult]) -> None:
    """Send header fields to review when they disagree with the client's own records: the imported vehicle list and the
    dates of the client's other invoices. The model is often confident about a misread digit; these checks are not."""
    import difflib
    import statistics

    fleet = [v for v in db.scalars(select(Vehicle)) if v.vehicle_class]  # the imported fleet list, not units made from invoices
    if fleet:
        by_unit = {_alnum(v.unit_number): v for v in fleet}
        by_vin = {v.vin: v for v in fleet if v.vin}
        unit, vin = h["unit_number"].value, h["vin"].value
        if unit:
            v = by_unit.get(_alnum(unit))
            if v is None:
                hint = by_vin.get(vin) if vin else None
                if hint is None:
                    close = difflib.get_close_matches(_alnum(unit), list(by_unit), n=1, cutoff=0.6)
                    hint = by_unit[close[0]] if close else None
                _lower(h["unit_number"], 0.5, f"Check this: unit {unit} isn't on the vehicle list." + (f" Did you mean {hint.unit_number}?" if hint else ""))
            else:
                if vin and v.vin and vin != v.vin:
                    _lower(h["vin"], 0.5, f"Check this: the vehicle list has VIN {v.vin} for unit {v.unit_number}.")
                odo = h["odometer"].value
                if odo is not None and v.start_odometer and odo < v.start_odometer:
                    _lower(h["odometer"], 0.5, f"Check this: lower than this unit's starting odometer on the vehicle list ({v.start_odometer:,}).")
    d = h["invoice_date"].value
    if d is not None:
        dates = [x for x in db.scalars(select(Invoice.invoice_date).where(Invoice.invoice_date.is_not(None)).limit(2000))]
        if len(dates) >= 5:
            mid = sorted(dates)[len(dates) // 2]
            if abs((d - mid).days) > 548:
                _lower(h["invoice_date"], 0.4, f"Check this: {d:%b %Y} is far from this client's other invoices (most are around {mid:%b %Y}).")


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
    # Fields with no arithmetic of their own (unit, odometer, invoice number) are compared with what the client already has.
    for field, note in crosschecks.run(db, shop_id=shop.id if shop else None, header=h):
        _lower(h[field], 0.5, note)

    # A VIN becomes a truck's identity only when it passes its check digit: one wrong character must not create or overwrite a VIN.
    good_vin = h["vin"].value if h["vin"].value and normalize.vin_check_digit_ok(h["vin"].value) else None
    vehicle = None
    if h["unit_number"].value:
        vehicle = db.scalar(select(Vehicle).where(Vehicle.unit_number == h["unit_number"].value))
        if not vehicle:
            vehicle = Vehicle(unit_number=h["unit_number"].value, vin=good_vin)
            db.add(vehicle)
            db.flush()
        elif not vehicle.vin and good_vin:
            vehicle.vin = good_vin

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
            page_no=(merged.line_meta[n - 1]["page"] if merged.line_meta and n - 1 < len(merged.line_meta) else None),
            y_center=(merged.line_meta[n - 1]["y"] if merged.line_meta and n - 1 < len(merged.line_meta) else None),
        )
        db.add(row)
        db.flush()
        for k, f in ln.items():
            if f.value not in (None, "") or f.failed_check:
                review |= _fc(db, "line", row.id, k, f, threshold)
        needs_job_type = cls.source != "fee" and (cls.code is None or cls.confidence < threshold)   # fee lines legitimately have no code
        db.add(FieldConfidence(record_type="line", record_id=row.id, field="vmrs_code", score=cls.confidence, needs_review=needs_job_type,
                               note="Check this: job type is a best guess." if needs_job_type else None))
        review |= needs_job_type
    inv.review_status = ReviewStatus.needs_review if review else ReviewStatus.ready
    db.flush()
    return inv


def retry_upload(db: Session, upload: Upload) -> None:
    from ..queue import enqueue

    upload.status, upload.status_detail = UploadStatus.queued, None
    db.commit()
    enqueue("extraction", "app.jobs.process_upload", str(upload.client_id), str(upload.id))
