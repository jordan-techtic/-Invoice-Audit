from datetime import date
from decimal import Decimal as D

from app.flags.types import Baseline, Context, InvoiceView, LineView, WarrantyView
from app.models import DEFAULT_CLIENT_SETTINGS

CFG = dict(DEFAULT_CLIENT_SETTINGS)


def L(inv_id="i1", n=1, code=None, hours=None, rate=None, price=None, qty=None, total=None, part=None, desc="work"):
    return LineView(id=f"{inv_id}-l{n}", invoice_id=inv_id, line_no=n, description=desc, part_number=part,
                    qty=D(str(qty)) if qty is not None else None, parts_price=D(str(price)) if price is not None else None,
                    labour_hours=D(str(hours)) if hours is not None else None, labour_rate=D(str(rate)) if rate is not None else None,
                    line_total=D(str(total)) if total is not None else None, vmrs_code=code)


def I(inv_id="i1", order=0, shop="acme", num=None, dt=None, unit="T1", odo=None, lines=(), subtotal=None, tax=None, total=None):
    return InvoiceView(id=inv_id, order=order, shop_key=shop, shop_name=shop, invoice_number=num, invoice_date=dt, unit_key=unit, odometer=odo,
                       subtotal=D(str(subtotal)) if subtotal is not None else None, tax=D(str(tax)) if tax is not None else None,
                       total=D(str(total)) if total is not None else None, lines=list(lines))


def ctx(invoices, **kw):
    cfg = {**CFG, **kw.pop("cfg", {})}
    return Context(invoices=list(invoices), config=cfg, **kw)


def d(y, m, dd):
    return date(y, m, dd)


def rule(code="031-001-001", name="Alternator", months=12, miles=100000):
    return {code: WarrantyView(code, name, months, miles)}
