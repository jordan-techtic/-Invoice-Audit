import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit
from ..deps import client_db, current_user
from ..models import Flag, FlagRun, FlagStatus, FlagType, Invoice, InvoiceLine, LabourBenchmark, Role, User, VmrsCode, WarrantyRule
from ..queue import enqueue

router = APIRouter(prefix="/clients/{client_id}", tags=["flags"])


def admin_only(client_id: uuid.UUID, user: User = Depends(current_user), _db: Session = Depends(client_db)) -> User:
    # depends on client_db so a user who can't see the client gets 404 before any role check
    if user.role != Role.admin:
        raise HTTPException(403, "Only admins can change this. Ask an admin to make the change.")
    return user


# ------------------------------------------------------------------ run + list


@router.post("/run-flags", status_code=202)
def run_flags(client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    busy = db.scalar(select(FlagRun.id).where(FlagRun.status.in_(["queued", "running"]),
                                              func.coalesce(FlagRun.started_at, FlagRun.created_at) > datetime.now(timezone.utc) - timedelta(minutes=15)).limit(1))
    if busy is not None:   # two runs at once delete and rebuild the same baselines and flags; a run stuck for 15 minutes is treated as dead
        raise HTTPException(409, "The checks are already running for this client. Wait for them to finish, then run them again.")
    run = FlagRun(status="queued")
    db.add(run)
    db.commit()
    audit.record(db, action="edit", object_type="flag_run", object_id=run.id, detail={"op": "run_flags"}, request=request)
    enqueue("flags", "app.jobs.run_flags", str(client_id), str(run.id))
    db.refresh(run)
    return {"job_id": str(run.id), "status": run.status}


@router.get("/flag-runs/{run_id}")
def flag_run(run_id: uuid.UUID, client_id: uuid.UUID, db: Session = Depends(client_db)):
    run = db.get(FlagRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return {"id": str(run.id), "status": run.status, "started_at": run.started_at, "finished_at": run.finished_at,
            "summary": run.summary or {"flags": 0, "by_type": {}, "notes": []}, "error": run.error, "cost_usd": float(run.cost_usd)}


@router.get("/flags")
def list_flags(client_id: uuid.UUID, type: str | None = None, status: str | None = None, shop: str | None = None, unit: str | None = None,
               sort: str = "impact_desc", db: Session = Depends(client_db)):
    base = select(Flag, Invoice, InvoiceLine).join(Invoice, Invoice.id == Flag.invoice_id).outerjoin(InvoiceLine, InvoiceLine.id == Flag.line_id)
    q = base
    if type:
        try:
            q = q.where(Flag.type == FlagType(type))
        except ValueError:
            raise HTTPException(422, "Unknown flag type. Pick a type from the list.")
    if status:
        try:
            q = q.where(Flag.status == FlagStatus(status))
        except ValueError:
            raise HTTPException(422, "Unknown status. Use open, accepted, edited or dismissed.")
    if shop:
        q = q.where(Invoice.shop_name_raw == shop)
    if unit:
        q = q.where(Invoice.unit_number == unit)
    if sort == "score_desc":   # the AI's view of how likely each flag is a real issue; flags it did not score go last
        q = q.order_by(Flag.ai_score.desc().nulls_last(), Flag.estimated_dollar_impact.desc(), Flag.created_at)
    else:
        q = q.order_by(Flag.estimated_dollar_impact.asc() if sort == "impact_asc" else Flag.estimated_dollar_impact.desc(), Flag.created_at)
    rows = db.execute(q).all()

    # Totals are plain sums of flag amounts, the same rule the report uses, so the screen and the report always agree.
    def total(statuses):
        return float(sum((f.estimated_dollar_impact for f, _i, _l in db.execute(base.where(Flag.status.in_(statuses))).all()), Decimal(0)))

    confirmed = total([FlagStatus.accepted, FlagStatus.edited])
    open_total = total([FlagStatus.open])
    return {
        "total_possible_recoverable": confirmed + open_total, "confirmed_total": confirmed, "open_total": open_total,
        "count": len(rows),
        "flags": [
            {"id": str(f.id), "type": f.type.value, "severity": f.severity.value, "impact": float(f.estimated_dollar_impact),
             "reason": f.plain_english_reason, "status": f.status.value, "ai_score": f.ai_score, "shop": inv.shop_name_raw,
             "unit": inv.unit_number, "invoice_id": str(inv.id), "invoice_number": inv.invoice_number,
             "line_description": ln.description if ln else None, "dismiss_reason": f.dismiss_reason, "note": f.analyst_note,
             "reviewed_at": f.reviewed_at, "evidence": f.details, "check_extraction_first": bool((f.details or {}).get("extraction_uncertain"))}
            for f, inv, ln in rows
        ],
    }


# ------------------------------------------------------------------ warranty rules


class RuleIn(BaseModel):
    vmrs_code: str
    component: str = Field(min_length=1, max_length=200)
    months: int = Field(ge=1, le=240)
    miles: int | None = Field(default=None, ge=1)
    covers: Literal["parts", "parts+labour"] = "parts+labour"


class RulePatch(BaseModel):
    component: str | None = Field(default=None, min_length=1, max_length=200)
    months: int | None = Field(default=None, ge=1, le=240)
    miles: int | None = Field(default=None, ge=1)
    covers: Literal["parts", "parts+labour"] | None = None
    clear_miles: bool = False


def _rule(r: WarrantyRule) -> dict:
    return {"id": str(r.id), "vmrs_code": r.vmrs_code, "component": r.component, "months": r.months, "miles": r.miles, "covers": r.covers}


@router.get("/warranty-rules")
def list_rules(client_id: uuid.UUID, db: Session = Depends(client_db)):
    return [_rule(r) for r in db.scalars(select(WarrantyRule).order_by(WarrantyRule.component))]


@router.post("/warranty-rules", status_code=201)
def add_rule(client_id: uuid.UUID, body: RuleIn, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    if db.get(VmrsCode, body.vmrs_code) is None:
        raise HTTPException(422, "That job code isn't in the VMRS list. Pick a code from the list.")
    if db.scalar(select(WarrantyRule).where(WarrantyRule.vmrs_code == body.vmrs_code)):
        raise HTTPException(409, "A warranty rule for that job code already exists. Edit it instead.")
    r = WarrantyRule(**body.model_dump())
    db.add(r)
    db.commit()
    audit.record(db, action="edit", object_type="warranty_rule", object_id=r.id, request=request)
    return _rule(r)


@router.put("/warranty-rules/{rule_id}")
def edit_rule(client_id: uuid.UUID, rule_id: uuid.UUID, body: RulePatch, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    r = db.get(WarrantyRule, rule_id)
    if r is None:
        raise HTTPException(404, "Warranty rule not found.")
    for k in ("component", "months", "miles", "covers"):
        v = getattr(body, k)
        if v is not None:
            setattr(r, k, v)
    if body.clear_miles:
        r.miles = None
    db.commit()
    audit.record(db, action="edit", object_type="warranty_rule", object_id=r.id, request=request)
    return _rule(r)


@router.delete("/warranty-rules/{rule_id}", status_code=204)
def delete_rule(client_id: uuid.UUID, rule_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    r = db.get(WarrantyRule, rule_id)
    if r is None:
        raise HTTPException(404, "Warranty rule not found.")
    db.delete(r)
    db.commit()
    audit.record(db, action="edit", object_type="warranty_rule", object_id=rule_id, detail={"op": "delete"}, request=request)


# ------------------------------------------------------------------ labour benchmarks


@router.get("/benchmarks")
def list_benchmarks(client_id: uuid.UUID, db: Session = Depends(client_db)):
    names = {c.code: c.component for c in db.scalars(select(VmrsCode))}
    rows = db.scalars(select(LabourBenchmark).order_by(LabourBenchmark.vmrs_code, LabourBenchmark.vehicle_class.nulls_first())).all()
    return [{"id": str(b.id), "vmrs_code": b.vmrs_code, "component": names.get(b.vmrs_code, b.vmrs_code), "vehicle_class": b.vehicle_class,
             "hours": float(b.benchmark_hours), "source": b.source, "sample_count": b.sample_count} for b in rows]


@router.post("/benchmarks/import")
async def import_benchmarks(client_id: uuid.UUID, request: Request, file: UploadFile = File(...), _: User = Depends(admin_only), db: Session = Depends(client_db)):
    raw = (await file.read(1_000_001))
    if len(raw) > 1_000_000:
        raise HTTPException(422, "That file is larger than 1 MB. Split it and import the parts.")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        cols = {c.strip().lower() for c in (reader.fieldnames or [])}
        if not {"vmrs_code", "benchmark_hours"} <= cols:
            raise HTTPException(422, "The CSV needs two columns named vmrs_code and benchmark_hours. Fix the header row and try again.")
        valid = {c.code for c in db.scalars(select(VmrsCode))}
        rows, seen = [], set()
        for n, row in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            code = row.get("vmrs_code", "")
            if code not in valid:
                raise HTTPException(422, f"Row {n}: '{code}' isn't a VMRS code we know. Check the code and import again.")
            try:
                hours = Decimal(row.get("benchmark_hours", ""))
            except InvalidOperation:
                raise HTTPException(422, f"Row {n}: '{row.get('benchmark_hours')}' isn't a number of hours. Enter it like 2.5.")
            if hours <= 0 or hours > 200:
                raise HTTPException(422, f"Row {n}: hours must be between 0 and 200.")
            if code in seen:
                raise HTTPException(422, f"Row {n}: '{code}' appears twice. Keep one row per code.")
            seen.add(code)
            rows.append((code, hours))
    except UnicodeDecodeError:
        raise HTTPException(422, "That file isn't a text CSV. Export it as CSV (UTF-8) and try again.")
    db.execute(delete(LabourBenchmark).where(LabourBenchmark.source == "licensed:import"))
    for code, hours in rows:
        db.add(LabourBenchmark(vmrs_code=code, benchmark_hours=hours, source="licensed:import"))
    db.commit()
    audit.record(db, action="edit", object_type="benchmarks", detail={"imported": len(rows)}, request=request)
    return {"imported": len(rows)}
