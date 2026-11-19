"""Evidence in simple terms, one short sentence per fact, for the review screen."""

from __future__ import annotations

from .types import hrs, money


def _n(x):
    return x if x is not None else 0


def evidence_lines(ftype: str, ev: dict, impact) -> list[str]:
    lines = _evidence_lines(ftype, ev, impact)
    if ev.get("extraction_uncertain"):
        lines = ["Some numbers behind this flag were hard to read on the invoice. Check them against the image before you accept it."] + lines
    return lines


def _evidence_lines(ftype: str, ev: dict, impact) -> list[str]:
    if ftype == "labour_over_benchmark":
        extra = ev["billed_hours"] - ev["benchmark_hours"]
        return [f"Billed {hrs(ev['billed_hours'])} hrs. Typical for this job: {hrs(ev['benchmark_hours'])} hrs.",
                f"That is {ev['over_pct']:.0f}% above typical (checks flag anything over {ev['threshold_pct']:.0f}%).",
                f"Extra time: {hrs(extra)} hrs x {money(ev['labour_rate'])} per hour = {money(impact)}."]
    if ftype == "repeat_repair":
        out = [f"The same job was done on this unit {ev['days_since_previous']} days earlier"
               + (f" and {ev['miles_since_previous']:,} miles earlier" if ev.get("miles_since_previous") is not None and ev["miles_since_previous"] >= 0 else "") + ".",
               f"Earlier invoice: {ev.get('previous_invoice') or 'unknown'}, dated {ev.get('previous_date')}.",
               f"Checks flag repeats within {ev['limit_days']} days or {ev['limit_miles']:,} miles."]
        return out
    if ftype == "warranty_eligible":
        w = f"{ev['warranty_months']} months" + (f" or {ev['warranty_miles']:,} miles" if ev.get("warranty_miles") else "")
        return [f"Earlier repair: invoice {ev.get('previous_invoice') or 'unknown'}, dated {ev.get('previous_date')}.",
                f"Replaced again {ev['days_since_previous']} days later"
                + (f" and {ev['miles_since_previous']:,} miles later" if ev.get("miles_since_previous") is not None and ev["miles_since_previous"] >= 0 else "") + ".",
                f"Warranty we assume for {ev['component'].lower()}: {w}."]
    if ftype == "parts_price_outlier":
        return [f"Billed {money(ev['unit_price'])} each for part {ev['part_number']}. Usual price: {money(ev['median_price'])}.",
                f"That is {ev['over_pct']:.0f}% above usual, based on {ev['samples']} invoices from {ev['shops_selling']} shop(s).",
                f"Extra cost: ({money(ev['unit_price'])} - {money(ev['median_price'])}) x {ev['qty']:g} = {money(impact)}."]
    if ftype == "duplicate":
        if ev.get("match") == "identical_line":
            return [f"This line appears twice with identical details (first on line {ev.get('first_line_no')}).", f"Amount counted twice: {money(impact)}."]
        why = "same shop and invoice number" if ev.get("match") == "same_number" else "same shop, unit, date and total"
        return [f"Matches invoice {ev.get('original_invoice_number') or 'already processed'} ({why}).", f"Total billed again: {money(impact)}."]
    if ftype == "math_error":
        if ev.get("check") == "line_total":
            return [f"Printed line total: {money(ev['printed_total'])}.", "Quantity, price and hours on the line add up to a different amount.", f"Difference: {money(impact)}."]
        names = {"lines_vs_subtotal": "The lines don't add up to the subtotal", "subtotal_tax_vs_total": "Subtotal plus tax doesn't equal the total"}
        out = [f"{names.get(f['check'], f['check'])}: difference {money(f['difference'])}." for f in ev.get("findings", [])]
        return out or [f"Difference: {money(impact)}."]
    return []
