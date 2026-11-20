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


# Notes written when an arithmetic or VIN check FAILS (as opposed to a field that is merely hard to read). The review step recognises a
# failed check by these phrases and will not mark the invoice "checked" until the field is corrected or confirmed as printed.
FAILED_CHECK_PHRASES = ("add up to", "doesn't equal the total", "don't equal the total", "check digit doesn't match", "a VIN has 17 characters")
NOTE_LOW = "Check this: hard to read on the invoice."
NOTE_MISSING = "Check this: not found on the invoice."


LINES_VS_TOTAL_NOTE = "Check this: the lines plus tax don't equal the total, so one of the line totals may be misread."


def _mark_line_totals(lines: list[dict[str, "FieldResult"]]) -> None:
    """A clearly read total that the lines don't reach usually means a line was misread (often one that adds up on its own,
    so the line check passes it). Mark every line total so the person compares each with the image, not only the total."""
    for ln in lines:
        if ln["line_total"].value is not None and LINES_VS_TOTAL_NOTE not in (ln["line_total"].note or ""):
            _lower(ln["line_total"], 0.6, LINES_VS_TOTAL_NOTE)


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
        # a note set before the checks (for example "two readings disagree") sends the field to review with that reason
        return FieldResult(d["value"], float(d["confidence"]), note=d.get("note"), failed_check=bool(d.get("note")))

    h = {k: fr(v) for k, v in merged_header.items()}

    # ---- header normalisation
    for k in ("shop_name", "shop_address", "invoice_number", "unit_number"):
        h[k].value = N.clean_text(h[k].value, 300 if k == "shop_address" else 200)
    h["invoice_date"].value = N.parse_date(h["invoice_date"].value) if h["invoice_date"].value is not None else None
    h["odometer"].value = N.parse_odometer(h["odometer"].value)
    for k in ("subtotal", "tax", "total"):
        h[k].value = N.parse_money(h[k].value)

    # values that cannot fit their database columns are treated as unreadable, never allowed to fail the invoice
    for k in ("unit_number", "invoice_number"):
        v = h[k].value
        if v is not None and len(v) > (50 if k == "unit_number" else 80):
            h[k].value, h[k].note = v[: 50 if k == "unit_number" else 80], "Check this: this value was unusually long and was cut short."
            h[k].confidence, h[k].failed_check = min(h[k].confidence, 0.4), True
    for k in ("subtotal", "tax", "total"):
        if h[k].value is not None and abs(h[k].value) >= Decimal("10000000000"):
            h[k].value = None
            _lower(h[k], 0.2, "Check this: couldn't be read as a valid amount.")

    # unparseable value that the model did report: ask a human
    for k, orig in (("invoice_date", merged_header["invoice_date"]["value"]), ("odometer", merged_header["odometer"]["value"])):
        if orig is not None and h[k].value is None:
            _lower(h[k], 0.3, "Check this: couldn't be read as a valid value.")

    vin, vstatus = N.normalize_vin(merged_header["vin"]["value"])
    # a short all-digit "VIN" is almost always the odometer read into the wrong field
    if vstatus == "bad_length" and vin and vin.isdigit() and 4 <= len(vin) <= 7 and h["odometer"].value is None:
        h["odometer"].value = N.parse_odometer(vin)
        h["odometer"].confidence = min(h["vin"].confidence, 0.5)
        h["odometer"].failed_check = True
        h["odometer"].note = "Check this: this number was read in the VIN position, so it is probably the odometer."
        h["vin"].value, h["vin"].confidence, vin, vstatus = None, 0.0, None, "missing"
    h["vin"].value = vin
    if vstatus == "bad_length":
        raw = vin or ""
        window = next((raw[i:i + 17] for i in range(len(raw) - 16) if N.vin_check_digit_ok(raw[i:i + 17])), None) if len(raw) > 17 else None
        if window:                                   # extra characters around a valid VIN (labels, spaces, a stray digit)
            h["vin"].value = window
            h["vin"].confidence = min(h["vin"].confidence, 0.6)
            h["vin"].failed_check = True
            h["vin"].note = f"Check this: the VIN was read with {len(raw)} characters; we kept the 17 that form a valid VIN."
        else:
            h["vin"].value = raw if len(raw) <= 17 else None   # never store more than a VIN column holds
            _lower(h["vin"], 0.4, f"Check this: a VIN has 17 characters and this one was read as {len(raw)}" + (f" ({raw[:40]})." if len(raw) > 17 else "."))
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
        for k, limit in (("parts_price", 10**10), ("labour_rate", 10**10), ("line_total", 10**10), ("qty", 10**8), ("labour_hours", 10**6)):
            if ln[k].value is not None and abs(ln[k].value) >= limit:
                ln[k].value = None
                _lower(ln[k], 0.2, "Check this: couldn't be read as a valid number.")
        ln["part_number"].value = ln["part_number"].value[:80] if ln["part_number"].value else None
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
            # Any one of these numbers may be the misread one, so every number on the line is marked, not just the total.
            for k in ("qty", "parts_price", "labour_hours", "labour_rate", "line_total"):
                if ln[k].value is not None:
                    _lower(ln[k], 0.6, "Check this: quantity, price and hours on this line don't add up to its total.")
            failed.append("line_math")
        elif price is not None and qty > 1 and lab == 0 and abs(price - lt) <= tolerance:
            _lower(ln["parts_price"], 0.6, f"Check this: the price for one equals the line total although the quantity is {qty}, so it may be the extended amount.")
            failed.append("price_is_extended")

    # ---- a labour-only line whose quantity just repeats its hours: the model copied one field into the other
    for ln in lines:
        q, hrs = ln["qty"].value, ln["labour_hours"].value
        if q is not None and hrs is not None and q == hrs and not ln["parts_price"].value:
            _lower(ln["qty"], 0.4, "Check this: the quantity is the same as the labour hours, so it may have been copied from them.")
            failed.append("qty_is_hours")

    # ---- invoice totals
    sub, tax, tot = h["subtotal"].value, h["tax"].value, h["total"].value
    line_sum = sum((ln["line_total"].value for ln in lines if ln["line_total"].value is not None), Decimal(0))
    # Most shops print "Parts / Labor / Tax / TOTAL DUE" with no Subtotal row, so the model may hand back one of those rows as the
    # subtotal. If the lines plus tax already equal the total, the invoice adds up and the subtotal is the doubtful number: do not fail the invoice.
    adds_up = (tot is not None and bool(lines) and all(ln["line_total"].value is not None for ln in lines) and line_sum > 0
               and abs(line_sum + (tax or Decimal(0)) - tot) <= tolerance)
    if sub is not None and not adds_up and lines and any(ln["line_total"].value is not None for ln in lines) and abs(line_sum - sub) > tolerance:
        _lower(h["subtotal"], 0.6, "Check this: the lines don't add up to the subtotal.")
        failed.append("subtotal_vs_lines")
    if sub is not None and tot is not None and not adds_up:
        if abs(sub + (tax or Decimal(0)) - tot) > tolerance:
            _lower(h["total"], 0.6, "Check this: subtotal plus tax doesn't equal the total.")
            failed.append("total_vs_subtotal_tax")
    elif sub is None and tot is not None and lines and abs(line_sum + (tax or Decimal(0)) - tot) > tolerance and line_sum > 0:
        total_was_clear = h["total"].confidence >= threshold   # read before it is lowered just below
        _lower(h["total"], 0.6, "Check this: the lines plus tax don't equal the total.")
        failed.append("total_vs_lines")
        if total_was_clear:
            _mark_line_totals(lines)
    # The subtotal agrees with the total but not with the lines: a line is the likely misread one.
    if (sub is not None and tot is not None and lines and all(ln["line_total"].value is not None for ln in lines)
            and abs(sub + (tax or Decimal(0)) - tot) <= tolerance and abs(line_sum - sub) > tolerance):
        _mark_line_totals(lines)

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
