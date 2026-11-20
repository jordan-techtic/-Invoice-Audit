"""Reference data in Settings: thresholds file, warranty rules CSV and the vehicle list. Admin only to change; staff with access can read."""

from __future__ import annotations

import uuid

from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..deps import client_db
from ..flags import reference as flag_reference
from ..models import Invoice, LabourBenchmark, User, Vehicle, VmrsCode, WarrantyRule
from ..services.normalize import normalize_vin
from ..services import reference_import as ri
from .flags import admin_only

router = APIRouter(prefix="/clients/{client_id}", tags=["reference data"])


def _problem(file_message: str | None = None, errors: list[ri.RowError] | None = None) -> JSONResponse:
    """422 with the human message in `detail` and every row problem in `errors`."""
    errors = errors or []
    if file_message:
        detail = file_message
    else:
        first = "; ".join(f"row {e.row}: {e.message}" if e.row else e.message for e in errors[:3])
        more = f" (and {len(errors) - 3} more)" if len(errors) > 3 else ""
        detail = f"{len(errors)} problem{'s' if len(errors) != 1 else ''} found in the file, so nothing was imported. {first}{more}"
    return JSONResponse(status_code=422, content={"detail": detail, "errors": [e.out() for e in errors]})


async def _read(file: UploadFile) -> bytes:
    return await file.read(ri.MAX_BYTES + 1)


@router.get("/vmrs-codes")
def list_codes(client_id: uuid.UUID, db: Session = Depends(client_db)):
    """The job codes the app knows, so a code can be picked instead of typed."""
    return [{"code": c.code, "component": c.component, "system": c.system} for c in db.scalars(select(VmrsCode).order_by(VmrsCode.code))]


# ------------------------------------------------------------------ thresholds


@router.post("/settings/import-thresholds")
async def import_thresholds(client_id: uuid.UUID, file: UploadFile = File(...), _: User = Depends(admin_only), db: Session = Depends(client_db)):
    """Read a thresholds file and return the values it holds. Nothing is saved: the page shows them in the form for review."""
    try:
        settings, applied, ignored = ri.thresholds_from_json(await _read(file))
    except ri.FileProblem as e:
        return _problem(e.message)
    return {"settings": settings, "applied": applied, "ignored": ignored}


# ------------------------------------------------------------------ warranty rules


@router.post("/warranty-rules/import")
async def import_warranty(client_id: uuid.UUID, request: Request, file: UploadFile = File(...), mode: str = Form("merge"),
                          _: User = Depends(admin_only), db: Session = Depends(client_db)):
    """CSV columns: component, warranty_months, warranty_miles ('unlimited' or blank = no limit), covers ('parts' or 'parts+labour').
    Optional: description (used to find the job code), vmrs_code (to name the code yourself). mode: merge (default) or replace."""
    if mode not in ("merge", "replace"):
        raise HTTPException(422, "mode must be 'merge' or 'replace'.")
    codes = list(db.scalars(select(VmrsCode)))
    try:
        parsed = ri.parse_warranty(await _read(file), codes)
    except ri.FileProblem as e:
        return _problem(e.message)
    if parsed.errors:
        return _problem(errors=parsed.errors)
    if mode == "replace":
        db.execute(delete(WarrantyRule))
        db.flush()
    existing = {r.vmrs_code: r for r in db.scalars(select(WarrantyRule))}
    added = updated = 0
    for r in parsed.rules:
        row = existing.get(r.vmrs_code)
        if row is None:
            db.add(WarrantyRule(vmrs_code=r.vmrs_code, component=r.component, months=r.months, miles=r.miles, covers=r.covers))
            added += 1
        else:
            row.component, row.months, row.miles, row.covers = r.component, r.months, r.miles, r.covers
            updated += 1
    db.commit()
    audit.record(db, action="edit", object_type="warranty_rules", detail={"op": "import", "mode": mode, "added": added, "updated": updated,
                                                                         "skipped": len(parsed.skipped)}, request=request)
    return {"rows": parsed.rows, "added": added, "updated": updated, "merged": parsed.merged, "skipped": parsed.skipped, "mode": mode,
            "total_rules": len(parsed.rules) if mode == "replace" else len(existing) + added}


# ------------------------------------------------------------------ vehicles


def _vehicle(v: Vehicle) -> dict:
    return {"id": str(v.id), "unit_number": v.unit_number, "vin": v.vin, "vehicle_class": v.vehicle_class, "year": v.year, "make": v.make,
            "model": v.model, "start_odometer": v.start_odometer}


@router.get("/vehicles")
def list_vehicles(client_id: uuid.UUID, db: Session = Depends(client_db)):
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.unit_number)).all()
    return [_vehicle(v) for v in vehicles]


@router.post("/vehicles/import")
async def import_vehicles(client_id: uuid.UUID, request: Request, file: UploadFile = File(...), _: User = Depends(admin_only),
                          db: Session = Depends(client_db)):
    """CSV columns: unit, vehicle_class (required); vin, year, make, model, start_odometer (optional). Units already on the list
    are updated, new ones are added; nothing is deleted."""
    try:
        parsed = ri.parse_vehicles(await _read(file))
    except ri.FileProblem as e:
        return _problem(e.message)
    if parsed.errors:
        return _problem(errors=parsed.errors)
    have = list(db.scalars(select(Vehicle)))
    by_exact = {v.unit_number: v for v in have}
    by_norm: dict[str, Vehicle] = {}
    for v in have:
        by_norm.setdefault(ri.norm_unit(v.unit_number), v)  # an invoice may have created 'T1001' for the list's 'T-1001'
    added = updated = 0
    for r in parsed.vehicles:
        v = by_exact.get(r.unit_number) or by_norm.get(ri.norm_unit(r.unit_number))
        if v is None:
            v = Vehicle(unit_number=r.unit_number)
            db.add(v)
            added += 1
        else:
            updated += 1
        v.vin = r.vin or v.vin
        v.vehicle_class, v.year, v.make, v.model, v.start_odometer = r.vehicle_class, r.year, r.make, r.model, r.start_odometer
    db.commit()
    audit.record(db, action="edit", object_type="vehicles", detail={"op": "import", "added": added, "updated": updated}, request=request)
    return {"rows": parsed.rows, "added": added, "updated": updated, "warnings": parsed.warnings, "total_vehicles": len(have) + added}


class VehicleIn(BaseModel):
    unit_number: str = Field(min_length=1, max_length=50)
    vehicle_class: str = Field(min_length=2, max_length=30)
    vin: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    start_odometer: int | None = Field(default=None, ge=0, le=10_000_000)


def _clean_vehicle(body: VehicleIn, db: Session, keep: Vehicle | None = None) -> dict:
    unit = body.unit_number.strip()
    cls = ri.norm_class(body.vehicle_class)
    if cls is None:
        raise HTTPException(422, "The vehicle class must be a short word like tractor, trailer, box_truck or van.")
    vin = None
    if body.vin and body.vin.strip():
        vin, status = normalize_vin(body.vin)
        if status == "bad_length":
            raise HTTPException(422, "A VIN is 17 characters.")
    for v in db.scalars(select(Vehicle)):
        if v is not keep and ri.norm_unit(v.unit_number) == ri.norm_unit(unit):
            raise HTTPException(409, f"Unit {v.unit_number} is already on the list. Edit that vehicle instead.")
    return {"unit_number": unit, "vehicle_class": cls, "vin": vin, "year": body.year, "make": (body.make or "").strip() or None,
            "model": (body.model or "").strip() or None, "start_odometer": body.start_odometer}


@router.post("/vehicles", status_code=201)
def add_vehicle(client_id: uuid.UUID, body: VehicleIn, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    v = Vehicle(**_clean_vehicle(body, db))
    db.add(v)
    db.commit()
    audit.record(db, action="edit", object_type="vehicle", object_id=v.id, detail={"op": "add"}, request=request)
    return _vehicle(v)


@router.put("/vehicles/{vehicle_id}")
def edit_vehicle(client_id: uuid.UUID, vehicle_id: uuid.UUID, body: VehicleIn, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(404, "Vehicle not found.")
    for k, val in _clean_vehicle(body, db, keep=v).items():
        setattr(v, k, val)
    db.commit()
    audit.record(db, action="edit", object_type="vehicle", object_id=v.id, detail={"op": "edit"}, request=request)
    return _vehicle(v)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(client_id: uuid.UUID, vehicle_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(404, "Vehicle not found.")
    db.execute(update(Invoice).where(Invoice.vehicle_id == v.id).values(vehicle_id=None))  # invoices keep the unit number they printed
    db.delete(v)
    db.commit()
    audit.record(db, action="delete", object_type="vehicle", object_id=vehicle_id, request=request)


@router.delete("/vehicles")
def delete_all_vehicles(client_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    db.execute(update(Invoice).where(Invoice.vehicle_id.is_not(None)).values(vehicle_id=None))
    n = db.execute(delete(Vehicle)).rowcount
    db.commit()
    audit.record(db, action="delete", object_type="vehicles", detail={"removed": n}, request=request)
    return {"removed": n}


@router.delete("/warranty-rules")
def delete_all_warranty_rules(client_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    n = db.execute(delete(WarrantyRule)).rowcount
    db.commit()
    audit.record(db, action="delete", object_type="warranty_rules", detail={"removed": n}, request=request)
    return {"removed": n}


# ------------------------------------------------------------------ labour benchmarks (typed in or imported; the computed ones are not editable)


class BenchmarkIn(BaseModel):
    vmrs_code: str
    benchmark_hours: Decimal = Field(gt=0, le=200)
    vehicle_class: str | None = None


@router.post("/benchmarks", status_code=201)
def add_benchmark(client_id: uuid.UUID, body: BenchmarkIn, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    if db.get(VmrsCode, body.vmrs_code) is None:
        raise HTTPException(422, "That job code isn't in the VMRS list. Pick a code from the list.")
    cls = None
    if body.vehicle_class and body.vehicle_class.strip():
        cls = ri.norm_class(body.vehicle_class)
        if cls is None:
            raise HTTPException(422, "The vehicle class must be a short word like tractor, trailer, box_truck or van, or blank for every vehicle.")
    clash = db.scalar(select(LabourBenchmark).where(LabourBenchmark.vmrs_code == body.vmrs_code, LabourBenchmark.source == "manual",
                                                    LabourBenchmark.vehicle_class.is_(None) if cls is None else LabourBenchmark.vehicle_class == cls))
    if clash:
        raise HTTPException(409, "You already added a benchmark for that job code and vehicle class. Remove it first, or add a different one.")
    b = LabourBenchmark(vmrs_code=body.vmrs_code, vehicle_class=cls, benchmark_hours=body.benchmark_hours, source="manual")
    db.add(b)
    db.commit()
    audit.record(db, action="edit", object_type="benchmarks", detail={"op": "add"}, request=request)
    return {"id": str(b.id)}


@router.delete("/benchmarks/{benchmark_id}", status_code=204)
def delete_benchmark(client_id: uuid.UUID, benchmark_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    b = db.get(LabourBenchmark, benchmark_id)
    if b is None:
        raise HTTPException(404, "Benchmark not found.")
    if b.source == flag_reference.CLIENT_SOURCE:
        raise HTTPException(409, "That one is worked out from this client's own invoices each time the checks run, so it can't be removed. Add your own value to override it.")
    db.delete(b)
    db.commit()
    audit.record(db, action="delete", object_type="benchmarks", detail={"op": "remove"}, request=request)


@router.delete("/benchmarks")
def delete_all_benchmarks(client_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    """Remove every benchmark that was typed in or imported. The ones computed from the client's invoices stay."""
    n = db.execute(delete(LabourBenchmark).where(LabourBenchmark.source != flag_reference.CLIENT_SOURCE)).rowcount
    db.commit()
    audit.record(db, action="delete", object_type="benchmarks", detail={"removed": n}, request=request)
    return {"removed": n}


@router.post("/benchmarks/import-jobs")
async def import_benchmark_jobs(client_id: uuid.UUID, request: Request, file: UploadFile = File(...), _: User = Depends(admin_only),
                                db: Session = Depends(client_db)):
    """CSV: a job list with a vehicle class (columns vehicle_class, benchmark_hours, and description / job_key / vmrs_code).
    Replaces the benchmarks imported this way before; typed-in and other imports are left alone."""
    codes = list(db.scalars(select(VmrsCode)))
    try:
        parsed = ri.parse_benchmark_jobs(await _read(file), codes)
    except ri.FileProblem as e:
        return _problem(e.message)
    if parsed.errors:
        return _problem(errors=parsed.errors)
    db.execute(delete(LabourBenchmark).where(LabourBenchmark.source == "licensed:jobs"))
    db.flush()
    for r in parsed.rows_out:
        db.add(LabourBenchmark(vmrs_code=r.vmrs_code, vehicle_class=r.vehicle_class, benchmark_hours=Decimal(r.hours), source="licensed:jobs"))
    db.commit()
    audit.record(db, action="edit", object_type="benchmarks", detail={"op": "import_jobs", "imported": len(parsed.rows_out), "skipped": len(parsed.skipped)}, request=request)
    return {"rows": parsed.rows, "imported": len(parsed.rows_out), "merged": parsed.merged, "skipped": parsed.skipped}
