"""Shared repair-history helper: previous repair of the same component on the same unit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..types import InvoiceView, LineView


@dataclass
class Prior:
    invoice: InvoiceView
    line: LineView
    days: int
    miles: int | None


def history(invoices: list[InvoiceView]) -> dict[tuple[str, str], list[tuple[InvoiceView, LineView]]]:
    """(unit, vmrs_code) -> repairs sorted oldest first. Needs a unit, a date and a code."""
    h: dict[tuple[str, str], list[tuple[InvoiceView, LineView]]] = {}
    for inv in invoices:
        if not inv.unit_key or not inv.invoice_date:
            continue
        for ln in inv.lines:
            if ln.vmrs_code:
                h.setdefault((inv.unit_key, ln.vmrs_code), []).append((inv, ln))
    for v in h.values():
        v.sort(key=lambda t: (t[0].invoice_date, t[0].order, t[1].line_no))
    return h


def prior_repair(entries: list[tuple[InvoiceView, LineView]], idx: int) -> Prior | None:
    """Most recent earlier repair on a *different* invoice (two sides on one invoice are not a repeat)."""
    inv, _ = entries[idx]
    for j in range(idx - 1, -1, -1):
        p_inv, p_ln = entries[j]
        if p_inv.id == inv.id:
            continue
        if inv.shop_key and p_inv.shop_key == inv.shop_key and inv.invoice_number and p_inv.invoice_number == inv.invoice_number:
            continue  # the same invoice seen twice: the duplicate rule covers it
        days = (inv.invoice_date - p_inv.invoice_date).days
        miles = inv.odometer - p_inv.odometer if inv.odometer is not None and p_inv.odometer is not None else None
        return Prior(p_inv, p_ln, days, miles)
    return None


def repair_amount(entries: list[tuple[InvoiceView, LineView]], idx: int) -> tuple[LineView, "Decimal"]:
    """First line of this repair (same invoice, same component) and the combined amount of all its lines."""
    from decimal import Decimal

    from ..types import line_amount

    inv, ln = entries[idx]
    same = [l for i, l in entries if i.id == inv.id]
    return same[0], sum((line_amount(l) for l in same), Decimal(0))
