"""Root causes behind the artifact items that were only partly fixed or not fixed (X5, X6, L9, L11, RP3, UI3).
Each test names the cause it pins. No dataset needed; the dataset version is tests/test_dataset_5.py."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import client_session
from app.flags.engine import load_views
from app.main import app
from app.models import FlagRun, Invoice, Vehicle, VmrsCache
from app.services.extraction.fake import FakeProvider

from .helpers import page_json, png_bytes, script
from .test_flags_engine import add_invoice
from .test_review import setup_flags
from .test_reports import decide, make

BAD_VIN = "1M8GDM9AXKP042789"      # last digit changed: fails the check digit
GOOD_VIN = "1M8GDM9AXKP042788"


def upload(c, cid, **kw):
    script(page_json(**kw))
    c.post(f"/clients/{cid}/uploads", files=[("files", (f"{kw.get('inv', 'x')}.png", png_bytes(seed=uuid.uuid4().int % 10**7), "image/png"))])
    return next(i for i in c.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == kw.get("inv", "48211"))


def header(c, cid, inv):
    return c.get(f"/clients/{cid}/invoices/{inv['id']}").json()["header"]


# ============================================================ X6: a VIN that fails its check digit must never become a truck's identity
def test_a_misread_vin_is_not_stored_on_the_vehicle(admin_client, world):
    cid = world["a"]
    upload(admin_client, cid, inv="VIN-1", unit="T-9", vin=BAD_VIN)
    with client_session(cid) as db:
        assert db.scalar(select(Vehicle).where(Vehicle.unit_number == "T-9")).vin is None


def test_a_valid_vin_is_stored_on_the_vehicle(admin_client, world):
    cid = world["a"]
    upload(admin_client, cid, inv="VIN-2", unit="T-8", vin=GOOD_VIN)
    with client_session(cid) as db:
        assert db.scalar(select(Vehicle).where(Vehicle.unit_number == "T-8")).vin == GOOD_VIN


def _vin_views(world, vin):
    with client_session(world["a"]) as db:
        a = add_invoice(db, "V1", date(2025, 1, 5), unit="T1", lines=[], total=D("100"))
        b = add_invoice(db, "V2", date(2025, 2, 5), unit=None, lines=[], total=D("100"))
        a.vin = b.vin = vin
        db.commit()
    with client_session(world["a"]) as db:
        return {v.invoice_number: v.unit_key for v in load_views(db)}


def test_an_invoice_with_no_unit_joins_a_truck_through_a_valid_vin(world):
    assert _vin_views(world, GOOD_VIN)["V2"] == "T1"


def test_an_invoice_with_no_unit_does_not_join_a_truck_through_a_misread_vin(world):
    assert _vin_views(world, BAD_VIN)["V2"] is None


# ============================================================ X5: fields with no arithmetic still get cross-checked against the client's own data
def test_a_unit_that_is_not_on_the_clients_vehicle_list_is_sent_to_review(admin_client, world):
    cid = world["a"]
    admin_client.post(f"/clients/{cid}/vehicles/import", files={"file": ("v.csv", b"unit,vehicle_class\nT-1,tractor\n", "text/csv")})
    bad = header(admin_client, cid, upload(admin_client, cid, inv="UN-1", unit="T-9"))["unit_number"]
    ok = header(admin_client, cid, upload(admin_client, cid, inv="UN-2", unit="T-1"))["unit_number"]
    assert bad["needs_review"] and "vehicle list" in bad["note"]
    assert not ok["needs_review"]


def test_without_a_vehicle_list_no_unit_is_questioned(admin_client, world):
    cid = world["a"]
    assert not header(admin_client, cid, upload(admin_client, cid, inv="UN-3", unit="T-77"))["unit_number"]["needs_review"]


def test_an_odometer_that_goes_backwards_for_the_same_unit_is_sent_to_review(admin_client, world):
    cid = world["a"]
    upload(admin_client, cid, inv="OD-1", unit="T-5", date="03/01/2026", odo="100,000")
    bad = header(admin_client, cid, upload(admin_client, cid, inv="OD-2", unit="T-5", date="04/01/2026", odo="10,000"))["odometer"]     # a digit lost
    ok = header(admin_client, cid, upload(admin_client, cid, inv="OD-3", unit="T-5", date="05/01/2026", odo="101,500"))["odometer"]
    assert bad["needs_review"] and "other invoices" in bad["note"]
    assert not ok["needs_review"]


def test_an_invoice_number_already_used_by_that_shop_for_a_different_job_is_sent_to_review(admin_client, world):
    cid = world["a"]
    upload(admin_client, cid, inv="48211", date="03/01/2026", total="580.00")
    other = header(admin_client, cid, upload(admin_client, cid, inv="48211", date="05/09/2026", unit="T-6", total="999.00", subtotal="999.00"))["invoice_number"]
    assert other["needs_review"] and "same number" in other["note"]      # a misread digit often lands on a number the shop already used


def test_a_true_resubmission_is_left_to_the_duplicate_rule_not_questioned_as_a_misread(admin_client, world):
    cid = world["a"]
    upload(admin_client, cid, inv="55555", date="03/01/2026", total="580.00")
    again = [i for i in (upload(admin_client, cid, inv="55555", date="03/04/2026", total="580.00"),)][0]
    assert not header(admin_client, cid, again)["invoice_number"]["needs_review"]          # same number AND same total


# ============================================================ L11: edits and learning
def test_an_overlong_unit_number_in_an_edit_is_a_clear_error_not_a_crash(admin_client, world):
    cid = world["a"]
    inv = upload(admin_client, cid, inv="LEN-1")
    r = admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "unit_number", "value": "T" * 60})
    assert r.status_code == 422 and "too long" in r.json()["detail"]
    r = admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "invoice_number", "value": "9" * 90})
    assert r.status_code == 422 and "too long" in r.json()["detail"]
    assert admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "unit_number", "value": "T-12"}).status_code == 200


def test_an_analysts_job_code_correction_is_remembered_for_the_same_description(admin_client, world):
    cid = world["a"]
    inv = upload(admin_client, cid, inv="LRN-1")
    line = admin_client.get(f"/clients/{cid}/invoices/{inv['id']}").json()["lines"][0]
    r = admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "vmrs_code", "value": "031-001-001", "line_id": line["id"]})
    assert r.status_code == 200
    from app.services.normalize import normalize_description
    with client_session(cid) as db:
        row = db.scalar(select(VmrsCache).where(VmrsCache.norm_description == normalize_description(line["description"]["value"])))
        assert row is not None and row.vmrs_code == "031-001-001" and row.source == "analyst"


# ============================================================ L9: two runs at once
def _running(cid, minutes_ago):
    with client_session(cid) as db:
        db.add(FlagRun(status="running", started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
        db.commit()


def test_a_second_flag_run_is_refused_while_one_is_running(admin_client, world):
    cid = world["a"]
    _running(cid, 1)
    r = admin_client.post(f"/clients/{cid}/run-flags")
    assert r.status_code == 409 and "already running" in r.json()["detail"]


def test_a_run_that_crashed_long_ago_does_not_block_new_runs_forever(admin_client, world):
    cid = world["a"]
    _running(cid, 90)
    assert admin_client.post(f"/clients/{cid}/run-flags").status_code == 202


# ============================================================ RP3: the next steps only mention what was found
def test_the_default_next_steps_mention_only_the_kinds_of_finding_in_the_report():
    from app.services.report_data import offer_text_for

    only_maths = offer_text_for({"math_error"})
    assert "correct" in only_maths.lower() and "warranty" not in only_maths.lower() and "duplicate" not in only_maths.lower()
    both = offer_text_for({"warranty_eligible", "duplicate"}).lower()
    assert "warranty" in both and "duplicate" in both and "monthly audit" in both


def test_a_report_without_typed_next_steps_uses_the_ones_that_fit_its_findings(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    snap = admin_client.get(f"/clients/{cid}/reports/{r.json()['id']}").json()
    types = {f["type"] for f in flags}
    text = snap["next_steps"]["text"].lower()
    assert ("warranty" in text) == bool(types & {"warranty_eligible", "repeat_repair"})
    assert ("duplicate" in text) == ("duplicate" in types)
    assert admin_client.get(f"/clients/{cid}/report-settings").json()["default_offer_text"]


# ============================================================ UI3: the public report link must not be indexed or leak its address
def test_public_report_responses_ask_not_to_be_indexed_or_referred(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    token = r.json()["share_url"].rsplit("/r/", 1)[1]
    for path in (f"/public/reports/{token}", f"/public/reports/{token}/pdf"):
        h = TestClient(app).get(path).headers
        assert "noindex" in h["x-robots-tag"] and h["referrer-policy"] == "no-referrer"
