"""Sanity checks and confidence handling on normalised extraction results.

A failed check lowers that field's confidence (so it lands in the review queue) and records a plain-language
note. The checks never change a value: they only ask a human to look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import normalize as N


@dataclass
class FieldResult:
    value: object
    confidence: float
    note: str | None = None
    failed_check: bool = False

    def needs_review(self, threshold: float) -> bool:
        return self.confidence < threshold or self.failed_check


@dataclass
class InvoiceResult:
    header: dict[str, FieldResult]
    lines: list[dict[str, FieldResult]]
    checks_failed: list[str] = field(default_factory=list)


NOTE_LOW = "Check this: hard to read on the invoice."
NOTE_MISSING = "Check this: not found on the invoice."


def _lower(fr: FieldResult, cap: float, note: str) -> None:
    fr.confidence = min(fr.confidence, cap)
    fr.failed_check = True
    fr.note = note if not fr.note else f"{fr.note} {note}"


def normalise_and_check(
    merged_header: dict[str, dict],
    merged_lines: list[dict[str, dict]],
    *,
    today: date | None = None,
    tolerance: Decimal = Decimal("1.00"),
    threshold: float = 0.80,
) -> InvoiceResult:
    today = today or date.today()
    failed: list[str] = []

    def fr(d: dict) -> FieldResult:
        return FieldResult(d["value"], float(d["confidence"]))

    h = {k: fr(v) for k, v in merged_header.items()}

    # ---- header normalisation
    for k in ("shop_name", "shop_address", "invoice_number", "unit_number"):
        h[k].value = N.clean_text(h[k].value, 300 if k == "shop_address" else 200)
    h["invoice_date"].value = N.parse_date(h["invoice_date"].value) if h["invoice_date"].value is not None else None
    h["odometer"].value = N.parse_odometer(h["odometer"].value)
    for k in ("subtotal", "tax", "total"):
        h[k].value = N.parse_money(h[k].value)

    # unparseable value that the model did report: ask a human
    for k, orig in (("invoice_date", merged_header["invoice_date"]["value"]), ("odometer", merged_header["odometer"]["value"])):
        if orig is not None and h[k].value is None:
            _lower(h[k], 0.3, "Check this: couldn't be read as a valid value.")

    vin, vstatus = N.normalize_vin(merged_header["vin"]["value"])
    h["vin"].value = vin
    if vstatus == "bad_length":
        _lower(h["vin"], 0.4, "Check this: a VIN has 17 characters and this one doesn't.")
        failed.append("vin_length")
    elif vstatus == "bad_check":
        _lower(h["vin"], 0.5, "Check this: the VIN's check digit doesn't match, so a character is probably misread.")
        failed.append("vin_check_digit")
    elif vstatus == "fixed":
        h["vin"].confidence = min(h["vin"].confidence, 0.9)

    d = h["invoice_date"].value
    if d is not None and d > today:
        _lower(h["invoice_date"], 0.4, "Check this: the date is in the future.")
        failed.append("date_future")

    # ---- lines
    lines: list[dict[str, FieldResult]] = []
    for raw in merged_lines:
        ln = {k: fr(v) for k, v in raw.items()}
        ln["description"].value = N.clean_text(ln["description"].value, 1000) or ""
        ln["part_number"].value = N.clean_id(ln["part_number"].value)
        for k in ("parts_price", "labour_rate", "line_total"):
            ln[k].value = N.parse_money(ln[k].value)
        for k in ("qty", "labour_hours"):
            ln[k].value = N.parse_number(ln[k].value)
        lines.append(ln)

    # ---- per-line arithmetic. Shops print "parts price" either per unit or already multiplied by qty,
    # so the line passes if it adds up under either reading.
    for ln in lines:
        lt = ln["line_total"].value
        if lt is None:
            continue
        price = ln["parts_price"].value
        qty = ln["qty"].value or Decimal(1)
        lab = ln["labour_hours"].value * ln["labour_rate"].value if ln["labour_hours"].value is not None and ln["labour_rate"].value is not None else Decimal(0)
        candidates = {lab} if price is None else {qty * price + lab, price + lab}
        if lab == 0 and price is None:
            continue
        if all(abs(c - lt) > tolerance for c in candidates):
            _lower(ln["line_total"], 0.6, "Check this: quantity, price and hours don't add up to this total.")
            failed.append("line_math")

    # ---- invoice totals
    sub, tax, tot = h["subtotal"].value, h["tax"].value, h["total"].value
    line_sum = sum((ln["line_total"].value for ln in lines if ln["line_total"].value is not None), Decimal(0))
    if sub is not None and lines and any(ln["line_total"].value is not None for ln in lines) and abs(line_sum - sub) > tolerance:
        _lower(h["subtotal"], 0.6, "Check this: the lines don't add up to the subtotal.")
        failed.append("subtotal_vs_lines")
    if sub is not None and tot is not None:
        if abs(sub + (tax or Decimal(0)) - tot) > tolerance:
            _lower(h["total"], 0.6, "Check this: subtotal plus tax doesn't equal the total.")
            failed.append("total_vs_subtotal_tax")
    elif sub is None and tot is not None and lines and abs(line_sum + (tax or Decimal(0)) - tot) > tolerance and line_sum > 0:
        _lower(h["total"], 0.6, "Check this: the lines plus tax don't equal the total.")
        failed.append("total_vs_lines")

    # ---- missing but expected
    for k in ("invoice_number", "invoice_date", "total", "shop_name"):
        if h[k].value is None:
            h[k].confidence = 0.0
            h[k].failed_check = True
            h[k].note = NOTE_MISSING

    # ---- low-confidence note
    for fr_ in list(h.values()) + [f for ln in lines for f in ln.values()]:
        if fr_.value is not None and fr_.confidence < threshold and not fr_.note:
            fr_.note = NOTE_LOW
    return InvoiceResult(h, lines, failed)
