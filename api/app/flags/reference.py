"""Reference data: labour benchmarks and parts price baselines, computed from the client's own invoices.

Pure functions work on views (unit tested); ``recompute`` persists the results. One function, run before every flag run.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import LabourBenchmark, PartsPriceBaseline
from .types import Baseline, InvoiceView, norm_part, unit_price

CLIENT_SOURCE = "client_median"


def _median(xs: list[Decimal]) -> Decimal:
    return Decimal(str(statistics.median(xs))).quantize(Decimal("0.01"))


def labour_medians(invoices: list[InvoiceView], min_samples: int) -> dict[str, tuple[Decimal, int]]:
    by: dict[str, list[Decimal]] = {}
    for inv in invoices:
        for ln in inv.lines:
            if ln.vmrs_code and ln.labour_hours is not None and ln.labour_hours > 0:
                by.setdefault(ln.vmrs_code, []).append(ln.labour_hours)
    return {c: (_median(v), len(v)) for c, v in by.items() if len(v) >= min_samples}


def labour_class_medians(invoices: list[InvoiceView], min_samples: int) -> dict[tuple[str, str], tuple[Decimal, int]]:
    """Typical hours per (job code, vehicle class), for units on the client's imported fleet list.
    The same job takes different time on a tractor and a trailer, so one median per code mixes them."""
    by: dict[tuple[str, str], list[Decimal]] = {}
    for inv in invoices:
        if not inv.vehicle_class:
            continue
        for ln in inv.lines:
            if ln.vmrs_code and ln.labour_hours is not None and ln.labour_hours > 0:
                by.setdefault((ln.vmrs_code, inv.vehicle_class), []).append(ln.labour_hours)
    return {k: (_median(v), len(v)) for k, v in by.items() if len(v) >= min_samples}


def _distinct(invoices: list[InvoiceView]) -> list[InvoiceView]:
    """Drop later copies of the same invoice (same shop and number): a re-billed copy is not independent evidence of a price or a job time."""
    seen: set[tuple] = set()
    out = []
    for inv in invoices:
        ident = (inv.shop_key, inv.invoice_number) if inv.shop_key and inv.invoice_number else None
        if ident is not None:
            if ident in seen:
                continue
            seen.add(ident)
        out.append(inv)
    return out


def parts_baselines(invoices: list[InvoiceView], min_samples: int) -> dict[str, Baseline]:
    prices: dict[str, list[Decimal]] = {}
    shops: dict[str, set] = {}
    sightings: dict[str, set] = {}
    for inv in _distinct(invoices):
        for ln in inv.lines:
            k, p = norm_part(ln.part_number), unit_price(ln)
            if k and p is not None and p > 0:
                prices.setdefault(k, []).append(p)
                shops.setdefault(k, set()).add(inv.shop_key)
                sightings.setdefault(k, set()).add(inv.id)     # one invoice is one sighting, however many lines carry the part
    return {k: Baseline(_median(v), len(sightings[k]), len(shops[k])) for k, v in prices.items() if len(sightings[k]) >= min_samples}


def recompute(db: Session, invoices: list[InvoiceView], cfg: dict) -> tuple[dict[str, Decimal], dict[str, Baseline]]:
    """Refresh stored baselines and return (benchmarks, baselines) for the rules. Licensed benchmarks win over computed ones."""
    now = datetime.now(timezone.utc)
    meds = labour_medians(invoices, int(cfg["labour_min_samples"]))
    db.execute(delete(LabourBenchmark).where(LabourBenchmark.source == CLIENT_SOURCE))
    for code, (hours, n) in meds.items():
        db.add(LabourBenchmark(vmrs_code=code, benchmark_hours=hours, sample_count=n, source=CLIENT_SOURCE))
    base = parts_baselines(invoices, int(cfg["parts_min_samples"]))
    db.execute(delete(PartsPriceBaseline))
    for k, b in base.items():
        db.add(PartsPriceBaseline(part_number=k, median_price=b.median, sample_count=b.samples, shop_count=b.shops, computed_at=now))
    db.flush()
    benchmarks = {code: hours for code, (hours, _) in meds.items()}
    for row in db.scalars(select(LabourBenchmark).where(LabourBenchmark.source != CLIENT_SOURCE, LabourBenchmark.vehicle_class.is_(None))):
        benchmarks[row.vmrs_code] = row.benchmark_hours  # per-class values are applied by the engine
    return benchmarks, base
