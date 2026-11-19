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


def parts_baselines(invoices: list[InvoiceView], min_samples: int) -> dict[str, Baseline]:
    prices: dict[str, list[Decimal]] = {}
    shops: dict[str, set] = {}
    for inv in invoices:
        for ln in inv.lines:
            k, p = norm_part(ln.part_number), unit_price(ln)
            if k and p is not None and p > 0:
                prices.setdefault(k, []).append(p)
                shops.setdefault(k, set()).add(inv.shop_key)
    return {k: Baseline(_median(v), len(v), len(shops[k])) for k, v in prices.items() if len(v) >= min_samples}


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
    for row in db.scalars(select(LabourBenchmark).where(LabourBenchmark.source != CLIENT_SOURCE)):
        benchmarks[row.vmrs_code] = row.benchmark_hours
    return benchmarks, base
