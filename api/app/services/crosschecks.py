"""Checks that compare a new invoice with what the client already has: fields with no arithmetic of their own (unit, odometer, invoice number).

A misread digit in these fields passes every check inside the one invoice, so the only way to notice is to compare it with the client's other data.
Like the other checks these never change a value: they lower the field's confidence and say why, so a person looks at the image.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Invoice, Vehicle


def norm_unit(u: str | None) -> str | None:
    return "".join(c for c in u.upper() if c.isalnum()) if u else None


class Fleet:
    """The client's imported vehicle list (vehicles that were given a class). Empty when the client has not imported one."""

    def __init__(self, unit_numbers: list[str]):
        self.units = {norm_unit(u) for u in unit_numbers if u}
        by_digits: dict[str, set[str]] = {}
        for u in self.units:
            by_digits.setdefault(u.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), set()).add(u)
        self._digits = {k: next(iter(v)) for k, v in by_digits.items() if k and len(v) == 1}

    @classmethod
    def load(cls, db: Session) -> "Fleet":
        return cls([v.unit_number for v in db.scalars(select(Vehicle).where(Vehicle.vehicle_class.is_not(None)))])

    def __bool__(self) -> bool:
        return bool(self.units)

    def resolve(self, unit: str | None) -> str | None:
        """The unit as the fleet list names it. A digits-only unit (a model dropped the letters of "T-1026") joins the one fleet unit with those digits."""
        n = norm_unit(unit)
        if n and n.isdigit() and n not in self.units:
            return self._digits.get(n, n)
        return n


def run(db: Session, *, shop_id, header: dict) -> list[tuple[str, str]]:
    """(field, note) for each header field of a NEW invoice that does not fit the client's other data. ``header`` maps field -> FieldResult."""
    out: list[tuple[str, str]] = []
    unit = header["unit_number"].value
    fleet = Fleet.load(db)
    if unit and fleet and fleet.resolve(unit) not in fleet.units:
        out.append(("unit_number", "Check this: this unit isn't on this client's vehicle list, so a character may be misread."))

    others = db.execute(select(Invoice.unit_number, Invoice.invoice_date, Invoice.odometer, Invoice.invoice_number, Invoice.total, Invoice.shop_id)).all()
    date, odo = header["invoice_date"].value, header["odometer"].value
    key = fleet.resolve(unit) if fleet else norm_unit(unit)
    if key and date and odo is not None:
        for o_unit, o_date, o_odo, *_ in others:
            if o_date is None or o_odo is None or o_date == date or (fleet.resolve(o_unit) if fleet else norm_unit(o_unit)) != key:
                continue
            if (o_date < date and o_odo > odo) or (o_date > date and o_odo < odo):
                out.append(("odometer", "Check this: the odometer doesn't fit this unit's other invoices (it goes backwards), so a digit may be misread."))
                break

    number, total = header["invoice_number"].value, header["total"].value
    if number and shop_id is not None and total is not None:
        for _u, _d, _o, o_number, o_total, o_shop in others:
            if o_shop == shop_id and o_number == number and o_total is not None and abs(Decimal(o_total) - Decimal(total)) > Decimal("1.00"):
                out.append(("invoice_number", "Check this: another invoice from this shop has the same number but a different total, so a digit may be misread."))
                break
    return out
