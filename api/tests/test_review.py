from sqlalchemy import select

from app.db import client_session
from app.models import Flag, FlagStatus
from app.services.extraction.fake import FakeProvider

from .test_flags_engine import seed_world


def setup_flags(admin_client, cid):
    FakeProvider.reset()
    seed_world(cid)
    assert admin_client.post(f"/clients/{cid}/run-flags").status_code == 202
    flags = admin_client.get(f"/clients/{cid}/flags").json()["flags"]
    assert len(flags) >= 2
    return flags


def audit_rows(admin_client, cid, action=None):
    q = f"?client_id={cid}" + (f"&action={action}" if action else "")
    return admin_client.get(f"/admin/audit-log{q}&limit=200").json()["rows"]


def test_accept_dismiss_edit_save_values_and_audit_log(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    a, b = flags[0], flags[1]
    r = admin_client.post(f"/clients/{cid}/flags/{a['id']}/accept", json={"note": "confirmed with shop"}).json()
    assert r["status"] == "accepted" and r["note"] == "confirmed with shop" and r["reviewed_by"] == "Admin" and r["reviewed_at"]
    d = admin_client.post(f"/clients/{cid}/flags/{b['id']}/dismiss", json={"reason": "valid_reason", "note": "extra rust"}).json()
    assert d["status"] == "dismissed" and d["dismiss_reason"] == "valid_reason" and d["reviewed_by"] == "Admin"
    if len(flags) > 2:
        c = flags[2]
        e = admin_client.post(f"/clients/{cid}/flags/{c['id']}/edit", json={"amount": 123.45, "reason": "Possible overbilling of about $123.", "note": "adjusted"}).json()
        assert e["status"] == "edited" and e["impact"] == 123.45 and e["original_impact"] == c["impact"]
        assert e["reason"].startswith("Possible overbilling") and e["original_reason"] == c["reason"] and e["note"] == "adjusted"
    with client_session(cid) as db:
        row = db.get(Flag, a["id"])
        assert row.reviewed_by is not None and row.reviewed_at is not None and row.analyst_note == "confirmed with shop"
    actions = [(x["action"], x["object_id"]) for x in audit_rows(admin_client, cid)]
    assert ("accept", a["id"]) in actions and ("dismiss", b["id"]) in actions
    if len(flags) > 2:
        assert ("edit", flags[2]["id"]) in actions


def test_validation_messages(admin_client, world):
    cid = world["a"]
    f = setup_flags(admin_client, cid)[0]
    base = f"/clients/{cid}/flags/{f['id']}"
    assert "Pick a reason" in admin_client.post(f"{base}/dismiss", json={"reason": "because"}).json()["detail"]
    assert admin_client.post(f"{base}/edit", json={}).status_code == 422
    assert admin_client.post(f"{base}/edit", json={"amount": -5}).status_code == 422
    assert admin_client.post(f"/clients/{cid}/flags/00000000-0000-0000-0000-000000000000/accept", json={}).status_code == 404


def test_totals_confirmed_vs_still_to_review_and_reopen(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    before = admin_client.get(f"/clients/{cid}/flags").json()
    assert before["confirmed_total"] == 0 and round(before["open_total"], 2) == round(sum(f["impact"] for f in flags), 2)
    f0 = flags[0]
    admin_client.post(f"/clients/{cid}/flags/{f0['id']}/accept", json={})
    mid = admin_client.get(f"/clients/{cid}/flags").json()
    assert mid["confirmed_total"] == f0["impact"] and round(mid["open_total"], 2) == round(before["open_total"] - f0["impact"], 2)
    r = admin_client.post(f"/clients/{cid}/flags/{f0['id']}/reopen").json()
    assert r["status"] == "open" and r["reviewed_by"] is None
    assert admin_client.get(f"/clients/{cid}/flags").json()["confirmed_total"] == 0


def test_filters_by_shop_and_unit(admin_client, world):
    cid = world["a"]
    setup_flags(admin_client, cid)
    f = admin_client.get(f"/clients/{cid}/flags/filters").json()
    assert "Acme Truck" in f["shops"] and f["units"]
    only = admin_client.get(f"/clients/{cid}/flags", params={"unit": f["units"][0], "shop": "Acme Truck"}).json()
    assert only["count"] >= 1 and all(x["unit"] == f["units"][0] for x in only["flags"])
    assert admin_client.get(f"/clients/{cid}/flags", params={"shop": "Nobody"}).json()["count"] == 0


def test_detail_has_plain_evidence_image_pages_and_flagged_line(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    lab = next(f for f in flags if f["type"] == "labour_over_benchmark")
    d = admin_client.get(f"/clients/{cid}/flags/{lab['id']}").json()
    assert d["evidence_lines"][0] == "Billed 4.0 hrs. Typical for this job: 2.0 hrs."
    assert d["line"]["line_no"] == 1 and sum(1 for l in d["lines"] if l["flagged"]) == 1
    assert d["invoice"]["pages"][0]["url"].startswith(f"/clients/{cid}/invoices/") and d["invoice"]["flagged_page"] == 1


def test_fix_field_then_recheck_updates_only_that_invoice(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    lab = next(f for f in flags if f["type"] == "labour_over_benchmark")
    others_before = {f["id"] for f in flags if f["invoice_id"] != lab["invoice_id"]}
    det = admin_client.get(f"/clients/{cid}/flags/{lab['id']}").json()
    inv = f"/clients/{cid}/invoices/{lab['invoice_id']}"
    assert admin_client.patch(f"{inv}/fields", json={"field": "labour_hours", "value": "2.0", "line_id": det["line"]["id"]}).status_code == 200
    r = admin_client.post(f"{inv}/recheck").json()
    assert r["removed"] >= 1
    after = admin_client.get(f"/clients/{cid}/flags").json()["flags"]
    assert lab["id"] not in {f["id"] for f in after}                      # the fixed finding is gone
    assert others_before <= {f["id"] for f in after}                      # other invoices' flags were not touched
    assert admin_client.post(f"{inv}/recheck").json()["removed"] == 0     # idempotent


def test_recheck_keeps_analyst_decisions(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    f = flags[0]
    admin_client.post(f"/clients/{cid}/flags/{f['id']}/accept", json={})
    admin_client.post(f"/clients/{cid}/invoices/{f['invoice_id']}/recheck")
    assert admin_client.get(f"/clients/{cid}/flags/{f['id']}").json()["status"] == "accepted"


def test_flags_built_on_unsure_extraction_say_so(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    lab = next(f for f in flags if f["type"] == "labour_over_benchmark")
    assert lab["check_extraction_first"] is False
    det = admin_client.get(f"/clients/{cid}/flags/{lab['id']}").json()
    from app.db import client_session as cs
    from app.models import FieldConfidence

    with cs(cid) as db:
        db.add(FieldConfidence(record_type="line", record_id=det["line"]["id"], field="labour_hours", score=0.5, needs_review=True))
        db.commit()
    admin_client.post(f"/clients/{cid}/invoices/{lab['invoice_id']}/recheck")
    # the open flag is refreshed with the marker
    again = next(f for f in admin_client.get(f"/clients/{cid}/flags").json()["flags"] if f["id"] == lab["id"])
    assert again["check_extraction_first"] is True
    d2 = admin_client.get(f"/clients/{cid}/flags/{lab['id']}").json()
    assert d2["evidence_lines"][0].startswith("Some numbers behind this flag were hard to read")
