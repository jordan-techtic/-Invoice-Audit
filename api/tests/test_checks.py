from datetime import date
from decimal import Decimal

from app.services.checks import normalise_and_check

H = lambda **o: {k: {"value": v, "confidence": 0.95} for k, v in {
    "shop_name": "S", "shop_address": None, "invoice_number": "1", "invoice_date": "03/14/2026", "unit_number": "T1",
    "vin": "1M8GDM9AXKP042788", "odometer": "100000", "subtotal": "100.00", "tax": "0.00", "total": "100.00", **o}.items()}
L = lambda total="100.00", **o: [{k: {"value": v, "confidence": 0.95} for k, v in {
    "description": "x", "part_number": None, "qty": 1, "parts_price": "100.00", "labour_hours": None, "labour_rate": None, "line_total": total, **o}.items()}]


def run(h, l):
    return normalise_and_check(h, l, today=date(2026, 6, 1))


def test_clean_invoice_has_no_failures():
    r = run(H(), L())
    assert r.checks_failed == []
    assert r.header["total"].value == Decimal("100.00") and r.header["invoice_date"].value == date(2026, 3, 14)


def test_total_mismatch_lowers_confidence_and_notes():
    r = run(H(total="130.00"), L())
    assert "total_vs_subtotal_tax" in r.checks_failed
    assert r.header["total"].confidence <= 0.6 and r.header["total"].failed_check and r.header["total"].note


def test_lines_not_adding_to_subtotal():
    assert "subtotal_vs_lines" in run(H(), L(total="90.00", parts_price=None)).checks_failed


def test_line_math_failure():
    r = run(H(subtotal="999.00", total="999.00"), L(total="999.00"))
    assert "line_math" in r.checks_failed


def test_future_date():
    assert "date_future" in run(H(invoice_date="12/01/2026"), L()).checks_failed


def test_bad_vin_flagged_but_value_kept():
    r = run(H(vin="1M8GDM9AXKP042789"), L())
    assert "vin_check_digit" in r.checks_failed and r.header["vin"].value == "1M8GDM9AXKP042789" and r.header["vin"].failed_check


def test_missing_total_needs_review():
    r = run(H(total=None), L())
    assert r.header["total"].failed_check and r.header["total"].note.startswith("Check this")


def test_line_math_accepts_extended_parts_price():
    # qty 4 and a parts amount that is already the extended price: both conventions are common on real invoices
    r = run(H(subtotal="200.00", total="200.00"), L(total="200.00", qty=4, parts_price="200.00"))
    assert "line_math" not in r.checks_failed
    r = run(H(subtotal="200.00", total="200.00"), L(total="200.00", qty=4, parts_price="50.00"))
    assert "line_math" not in r.checks_failed
