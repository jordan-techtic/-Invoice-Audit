"""Plain data views the rules work on, so rules are pure functions with no database."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class LineView:
    id: str
    invoice_id: str
    line_no: int
    description: str = ""
    part_number: str | None = None
    qty: Decimal | None = None
    parts_price: Decimal | None = None
    labour_hours: Decimal | None = None
    labour_rate: Decimal | None = None
    line_total: Decimal | None = None
    vmrs_code: str | None = None


@dataclass
class InvoiceView:
    id: str
    order: int  # processing order; the earliest copy of a duplicate is treated as the original
    shop_key: str | None = None
    shop_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    unit_key: str | None = None
    odometer: int | None = None
    vehicle_class: str | None = None  # from the client's imported fleet list, when the unit is on it
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    lines: list[LineView] = field(default_factory=list)


@dataclass
class WarrantyView:
    vmrs_code: str
    component: str
    months: int
    miles: int | None
    covers: str = "parts+labour"  # "parts" or "parts+labour"


@dataclass
class Baseline:
    median: Decimal
    samples: int
    shops: int


@dataclass
class Context:
    invoices: list[InvoiceView]
    config: dict
    benchmarks: dict[str, Decimal] = field(default_factory=dict)  # vmrs_code -> typical hours
    class_benchmarks: dict[tuple[str, str], Decimal] = field(default_factory=dict)  # (vmrs_code, vehicle class) -> typical hours
    baselines: dict[str, Baseline] = field(default_factory=dict)  # normalised part number -> baseline
    warranty: dict[str, WarrantyView] = field(default_factory=dict)
    code_names: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class FlagDraft:
    type: str  # FlagType value
    invoice_id: str
    line_id: str | None
    impact: Decimal
    evidence: dict
    template_reason: str
    dedupe_key: str
    related_invoice_id: str | None = None


def norm_part(p: str | None) -> str | None:
    if not p:
        return None
    s = re.sub(r"[^A-Z0-9]", "", p.upper())
    return s or None


def money(d: Decimal | float | int) -> str:
    d = Decimal(str(d)).quantize(Decimal("0.01"))
    return f"${d:,.0f}" if d == d.to_integral_value() else f"${d:,.2f}"


def hrs(d: Decimal | float) -> str:
    return f"{Decimal(str(d)).quantize(Decimal('0.1'))}"


def line_amount(line: LineView) -> Decimal:
    """What a line cost: its printed total, else parts + labour."""
    if line.line_total is not None:
        return line.line_total
    parts = (line.qty or Decimal(1)) * line.parts_price if line.parts_price is not None else Decimal(0)
    lab = line.labour_hours * line.labour_rate if line.labour_hours is not None and line.labour_rate is not None else Decimal(0)
    return parts + lab


def parts_amount(line: LineView) -> Decimal:
    """The parts part of a line: its cost minus any labour on it (zero for a labour-only line)."""
    lab = _labour(line) or Decimal(0)
    if line.parts_price is None and lab > 0:
        return Decimal(0)
    return max(line_amount(line) - lab, Decimal(0))


def _labour(line: LineView) -> Decimal | None:
    return line.labour_hours * line.labour_rate if line.labour_hours is not None and line.labour_rate is not None else None


def unit_price_candidates(line: LineView, tol: Decimal = Decimal("1.00")) -> list[Decimal]:
    """Possible per-unit parts prices. Shops print the unit price or the extended amount; the line total can tell which,
    but not when labour is billed as a lump sum. Returns one value when certain, two when ambiguous, none if unknown."""
    p = line.parts_price
    if p is None:
        return []
    qty = line.qty if line.qty and line.qty > 0 else Decimal(1)
    if qty == 1:
        return [p]
    if line.line_total is not None:
        lab = _labour(line) or Decimal(0)
        if abs(qty * p + lab - line.line_total) <= tol:
            return [p]
        if abs(p + lab - line.line_total) <= tol:
            return [p / qty]
    return [p, p / qty]


def unit_price(line: LineView, tol: Decimal = Decimal("1.00")) -> Decimal | None:
    """Per-unit price when it can be determined for certain, else None (ambiguous lines are left out of baselines)."""
    c = unit_price_candidates(line, tol)
    return c[0] if len(c) == 1 else None


def severity(impact: Decimal, cfg: dict) -> str:
    if impact >= Decimal(str(cfg["severity_high_dollars"])):
        return "high"
    if impact >= Decimal(str(cfg["severity_medium_dollars"])):
        return "medium"
    return "low"
