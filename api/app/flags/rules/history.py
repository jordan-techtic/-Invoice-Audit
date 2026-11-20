"""Shared repair-history helper: previous repair of the same component on the same unit."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..types import InvoiceView, LineView


@dataclass
class Prior:
    invoice: InvoiceView
    line: LineView
    days: int
    miles: int | None


# ---- a part has a position, and inspecting it is not replacing it
_SIDE = {"lh": "L", "left": "L", "driver": "L", "drvr": "L", "drv": "L", "lf": "L", "lr": "L",
         "rh": "R", "right": "R", "passenger": "R", "pass": "R", "psgr": "R", "rf": "R", "rr": "R"}
_AXLE = {"front": "F", "frt": "F", "fr": "F", "lf": "F", "rf": "F", "rear": "B", "lr": "B", "rr": "B"}
_REMOVE_REPLACE = re.compile(r"\br\s*[/&]\s*r\b", re.I)          # "R/R" and "R&R" mean remove-and-replace, not a position
_INSPECT = re.compile(r"\b(inspect\w*|insp|check\w*|adjust\w*|test\w*|diagnos\w*|diag|measure\w*)\b", re.I)
_REPLACE = re.compile(r"\b(replac\w*|rplc\w*|install\w*|swap\w*|new)\b|\br\s*[/&]\s*r\b", re.I)


def position_of(description: str | None) -> tuple[str | None, str | None]:
    """(side, axle) read from words like LF, RH, driver, passenger, front, rear. Unknown parts stay None."""
    side = axle = None
    for tok in re.findall(r"[a-z]+", _REMOVE_REPLACE.sub(" ", (description or "").lower())):
        side = side or _SIDE.get(tok)
        axle = axle or _AXLE.get(tok)
    return side, axle


def positions_conflict(a: str | None, b: str | None) -> bool:
    """True only when both descriptions name a side (or an axle) and they differ. A position that is not printed is not a conflict."""
    (sa, xa), (sb, xb) = position_of(a), position_of(b)
    return bool(sa and sb and sa != sb) or bool(xa and xb and xa != xb)


def is_replacement(description: str | None) -> bool:
    """False for work that is only looking at, checking or adjusting a part; such a line is not an earlier repair to repeat or claim on."""
    d = description or ""
    return not (_INSPECT.search(d) and not _REPLACE.search(d))


def history(invoices: list[InvoiceView]) -> dict[tuple[str, str], list[tuple[InvoiceView, LineView]]]:
    """(unit, vmrs_code) -> repairs sorted oldest first. Needs a unit, a date and a code."""
    h: dict[tuple[str, str], list[tuple[InvoiceView, LineView]]] = {}
    for inv in invoices:
        if not inv.unit_key or not inv.invoice_date:
            continue
        for ln in inv.lines:
            if ln.vmrs_code and is_replacement(ln.description):
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
        if days < 1:
            continue  # the same day: a continuation of the job or a re-bill (the duplicate rule covers that), not a repeat
        if positions_conflict(entries[idx][1].description, p_ln.description):
            continue  # a different wheel position or axle is a different part
        miles = inv.odometer - p_inv.odometer if inv.odometer is not None and p_inv.odometer is not None else None
        return Prior(p_inv, p_ln, days, miles)
    return None


def repair_lines(entries: list[tuple[InvoiceView, LineView]], idx: int) -> list[LineView]:
    """Every line of this repair (same invoice, same component)."""
    inv, _ = entries[idx]
    return [l for i, l in entries if i.id == inv.id]


def repair_amount(entries: list[tuple[InvoiceView, LineView]], idx: int) -> tuple[LineView, "Decimal"]:
    """First line of this repair (same invoice, same component) and the combined amount of all its lines."""
    from decimal import Decimal

    from ..types import line_amount

    inv, ln = entries[idx]
    same = [l for i, l in entries if i.id == inv.id]
    return same[0], sum((line_amount(l) for l in same), Decimal(0))
