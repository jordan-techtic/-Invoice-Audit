"""The six review fixes: photo copies de-duplicated, checks against the client's own records, 'mark as checked' needs every
field looked at, job codes for PM / inspections and split components, the tax-rate check, and the AI rating in the API."""

import csv
import types
import uuid
from decimal import Decimal as D

from app.db import client_session
from app.flags.rules import math_errors
from app.models import Vehicle
from app.services.normalize import normalize_description
from app.services.vmrs import lookup

from .flag_helpers import I, L, ctx
from .helpers import page_json, png_bytes, script


def upload(c, cid, body: str, name="x.png"):
    script(body)
    return c.post(f"/clients/{cid}/uploads", files=[("files", (name, png_bytes(seed=uuid.uuid4().int % 10**7), "image/png"))]).json()[0]["upload"]


# ------------------------------------------------------------------ 1. a second photo of the same invoice
def test_a_second_photo_of_the_same_invoice_is_skipped_not_flagged(admin_client, world):
    cid = world["a"]
    num = f"P-{uuid.uuid4().hex[:5]}"
    first = upload(admin_client, cid, page_json(inv=num), "scan.pdf.png")
    again = upload(admin_client, cid, page_json(inv=num), "IMG_0001.png")       # different file bytes, same paper
    assert first["status"] in ("done", "needs_review")
    assert again["status"] == "duplicate" and "same invoice" in again["status_detail"] and again["duplicate_of"] == first["id"]
    assert sum(1 for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == num) == 1
    resubmitted = upload(admin_client, cid, page_json(inv=num + "B"))           # a new number is billing again: kept for the duplicate rule
    assert resubmitted["status"] != "duplicate"


# ------------------------------------------------------------------ 2a. checks against the vehicle list and other invoices
def test_unit_not_on_the_vehicle_list_goes_to_review_with_a_suggestion(admin_client, world):
    cid = world["a"]
    with client_session(cid) as db:
        db.add(Vehicle(unit_number="T-1038", vehicle_class="tractor", vin="1M8GDM9AXKP042788", start_odometer=500000))
        db.commit()
    upload(admin_client, cid, page_json(inv="U-1", unit="T-108"))             # misread unit, VIN read right
    inv = next(i for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == "U-1")
    h = admin_client.get(f"/clients/{cid}/invoices/{inv['id']}").json()["header"]
    assert h["unit_number"]["needs_review"] and "isn't on the vehicle list" in h["unit_number"]["note"] and "T-1038" in h["unit_number"]["note"]
    upload(admin_client, cid, page_json(inv="U-2", unit="T-1038", odo="412,880"))   # on the list, but below its starting odometer
    inv = next(i for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == "U-2")
    h = admin_client.get(f"/clients/{cid}/invoices/{inv['id']}").json()["header"]
    assert not h["unit_number"]["needs_review"] and h["odometer"]["needs_review"] and "starting odometer" in h["odometer"]["note"]


def test_a_date_far_from_the_clients_other_invoices_goes_to_review(admin_client, world):
    cid = world["a"]
    for n in range(5):
        upload(admin_client, cid, page_json(inv=f"D-{n}", date=f"03/{10 + n}/2026"))
    upload(admin_client, cid, page_json(inv="D-odd", date="03/14/2020"))      # 2026 misread as 2020
    inv = next(i for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == "D-odd")
    h = admin_client.get(f"/clients/{cid}/invoices/{inv['id']}").json()["header"]
    assert h["invoice_date"]["needs_review"] and "far from this client's other invoices" in h["invoice_date"]["note"]


# ------------------------------------------------------------------ 2b. 'mark as checked' needs every flagged field looked at
def test_mark_as_checked_is_refused_until_each_flagged_field_is_fixed_or_confirmed(admin_client, world):
    cid = world["a"]
    body = page_json(inv="C-1").replace('"odometer": {"value": "412,880", "confidence": 0.95}', '"odometer": {"value": "412,880", "confidence": 0.5}')
    upload(admin_client, cid, body)
    iid = next(i["id"] for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == "C-1")
    r = admin_client.post(f"/clients/{cid}/invoices/{iid}/mark-checked")
    assert r.status_code == 409 and "still marked Check" in r.json()["detail"]
    assert admin_client.post(f"/clients/{cid}/invoices/{iid}/fields/confirm", json={"field": "total"}).status_code == 409   # wasn't flagged
    assert admin_client.post(f"/clients/{cid}/invoices/{iid}/fields/confirm", json={"field": "odometer"}).json()["fields_to_check"] == 0
    assert admin_client.post(f"/clients/{cid}/invoices/{iid}/mark-checked").json()["review_status"] == "reviewed"


# ------------------------------------------------------------------ 3/4. job codes
def _codes():
    return [types.SimpleNamespace(**r) for r in csv.DictReader(open("app/data/vmrs_codes.csv"))]


def test_pm_services_inspections_and_split_components_have_their_own_codes():
    codes = _codes()
    got = {t: getattr(lookup(normalize_description(t), codes), "code", None) for t in
           ["PM-A service", "PM-B svc", "Trailer PM inspection", "DOT annual inspection", "Annual DOT insp", "R&R U-joint",
            "DPF clean & bake", "R&R DPF", "R&R NOx sensor", "R&R DEF doser", "R&R EGR cooler", "R&R EGR valve",
            "R&R belt tensioner", "Replace serpentine belt", "Replace wiper blades", "R&R wiper motor", "PM service"]}
    assert got == {"PM-A service": "000-001-001", "PM-B svc": "000-001-002", "Trailer PM inspection": "000-001-003",
                   "DOT annual inspection": "000-001-004", "Annual DOT insp": "000-001-004", "R&R U-joint": "024-001-001",
                   "DPF clean & bake": "043-001-005", "R&R DPF": "043-001-001", "R&R NOx sensor": "043-001-006", "R&R DEF doser": "043-001-002",
                   "R&R EGR cooler": "043-001-007", "R&R EGR valve": "043-001-003", "R&R belt tensioner": "045-001-009",
                   "Replace serpentine belt": "045-001-007", "Replace wiper blades": "002-001-006", "R&R wiper motor": "002-001-005",
                   "PM service": "045-001-001"}


def test_routine_pm_and_inspections_are_never_repeat_repairs():
    from datetime import date

    from app.flags.rules import repeat
    a = I("a", 0, num="1", dt=date(2025, 1, 1), lines=[L("a", code="000-001-004", total=200)])
    b = I("b", 1, num="2", dt=date(2025, 1, 20), lines=[L("b", code="000-001-004", total=200)])
    assert repeat.run(ctx([a, b])) == []


# ------------------------------------------------------------------ 5. tax rate
def _taxed(i, rate, parts=D("400.00"), labour_hours=D("2"), shop="acme"):
    tax = (parts * rate).quantize(D("0.01"))
    total = parts + labour_hours * 100 + tax
    return I(f"i{i}", i, shop=shop, num=str(i), lines=[L(f"i{i}", 1, price=parts, qty=1, total=parts), L(f"i{i}", 2, hours=labour_hours, rate=100, total=labour_hours * 100)],
             subtotal=parts + labour_hours * 100, tax=tax, total=total)


def test_tax_charged_above_the_shops_usual_rate_is_flagged_for_the_extra_only():
    invs = [_taxed(n, D("0.0825")) for n in range(4)] + [_taxed(9, D("0.0975"))]
    f = [d for d in math_errors.run(ctx(invs)) if d.evidence.get("check") == "tax_rate"]
    assert len(f) == 1 and f[0].invoice_id == "i9" and f[0].impact == D("6.00")         # 400 x (9.75% - 8.25%)
    assert f[0].evidence["usual_rate_pct"] == 8.25 and f[0].evidence["taxed_on"] == "parts"


def test_tax_check_needs_enough_invoices_from_that_shop_and_ignores_small_drift():
    few = [_taxed(n, D("0.0825")) for n in range(2)] + [_taxed(9, D("0.0975"))]
    assert not [d for d in math_errors.run(ctx(few)) if d.evidence.get("check") == "tax_rate"]
    drift = [_taxed(n, D("0.0825")) for n in range(4)] + [_taxed(9, D("0.0830"))]
    assert not [d for d in math_errors.run(ctx(drift)) if d.evidence.get("check") == "tax_rate"]
    lower = [_taxed(n, D("0.0825")) for n in range(4)] + [_taxed(9, D("0.0700"))]          # under-charging is not recoverable
    assert not [d for d in math_errors.run(ctx(lower)) if d.evidence.get("check") == "tax_rate"]


def test_tax_settings_are_validated(admin_client, world):
    url = f"/clients/{world['a']}"
    assert admin_client.patch(url, json={"settings": {"tax_min_invoices": 5, "tax_rate_tolerance_pct": 0.5}}).status_code == 200
    assert admin_client.patch(url, json={"settings": {"tax_rate_tolerance_pct": -1}}).status_code == 422


# ------------------------------------------------------------------ 6. AI rating
def test_ai_rating_is_returned_and_flags_can_be_sorted_by_it(admin_client, world):
    from .test_review import setup_flags

    cid = world["a"]
    setup_flags(admin_client, cid)
    flags = admin_client.get(f"/clients/{cid}/flags?status=&sort=score_desc").json()["flags"]
    assert flags and all("ai_score" in f for f in flags)
    scores = [f["ai_score"] for f in flags]
    rated = [s for s in scores if s is not None]
    assert rated == sorted(rated, reverse=True) and scores[: len(rated)] == rated   # rated first, highest first; unrated last
    detail = admin_client.get(f"/clients/{cid}/flags/{flags[0]['id']}").json()
    assert "ai_score" in detail
