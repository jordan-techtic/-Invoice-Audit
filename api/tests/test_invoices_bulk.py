import uuid

from sqlalchemy import select

from app.db import client_session
from app.models import FieldConfidence, Flag, Invoice, InvoiceLine, Upload
from app.services.extraction.fake import FakeProvider

from .helpers import page_json, png_bytes, script
from .test_reports import decide, pdf_text
from .test_review import setup_flags


def seed(c, cid, n=4, tag="B"):
    """n uploaded invoices, each with one low-confidence field so they start as 'needs review'. Returns [(invoice_id, upload_id)]."""
    out = []
    for i in range(n):
        low = page_json(inv=f"{tag}-{uuid.uuid4().hex[:5]}").replace('"odometer": {"value": "412,880", "confidence": 0.95}', '"odometer": {"value": "412,880", "confidence": 0.5}')
        script(low)
        up = c.post(f"/clients/{cid}/uploads", files=[("files", (f"b{i}.png", png_bytes(seed=uuid.uuid4().int % 10**7), "image/png"))]).json()[0]["upload"]
        out.append(up)
    invs = [i for i in c.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] and i["invoice_number"].startswith(f"{tag}-")]
    assert len(invs) == n and all(i["review_status"] == "needs_review" for i in invs)
    return invs, out


def test_bulk_check_marks_many_and_updates_uploads(admin_client, world):
    cid = world["a"]
    invs, ups = seed(admin_client, cid, 4)
    ids = [i["id"] for i in invs]
    blocked = admin_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": ids[:3]}).json()
    assert blocked["checked"] == 0 and blocked["already_checked"] == 0 and blocked["skipped"] == 0   # each has a field marked Check: nothing waved through
    assert sorted(b["id"] for b in blocked["blocked"]) == sorted(ids[:3]) and all(b["fields"] == ["odometer"] for b in blocked["blocked"])
    for i in ids[:3]:                                                                       # the analyst looks at the image and confirms it
        assert admin_client.post(f"/clients/{cid}/invoices/{i}/fields/confirm", json={"field": "odometer"}).json()["fields_to_check"] == 0
    r = admin_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": ids[:3]}).json()
    assert r == {"checked": 3, "already_checked": 0, "skipped": 0}   # no "blocked" key when nothing was held back
    now = {i["id"]: i for i in admin_client.get(f"/clients/{cid}/invoices").json()}
    assert [now[i]["review_status"] for i in ids] == ["reviewed"] * 3 + ["needs_review"] and now[ids[0]]["fields_to_check"] == 0
    odo = admin_client.get(f"/clients/{cid}/invoices/{ids[0]}").json()["header"]["odometer"]
    assert odo["needs_review"] is False and odo["confidence"] == 0.5   # confirmed, and the low score stays visible
    statuses = {u["id"]: u["status"] for u in admin_client.get(f"/clients/{cid}/uploads").json()}
    assert [statuses[u["id"]] for u in ups[::-1]] == ["done"] * 3 + ["needs_review"]   # invoices are listed newest first; an upload is done once its invoice is checked
    again = admin_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": ids}).json()
    assert again["checked"] == 0 and again["already_checked"] == 3 and [b["id"] for b in again["blocked"]] == [ids[3]]   # safe to repeat; the 4th still needs its field looked at
    rows = admin_client.get(f"/admin/audit-log?client_id={cid}&action=edit&limit=50").json()["rows"]
    assert any(x["detail"].get("op") == "bulk_mark_checked" and x["detail"]["count"] == 3 for x in rows)


def test_bulk_check_ignores_unknown_and_other_clients_ids_and_validates_size(admin_client, world):
    a, b = world["a"], world["b"]
    mine, _ = seed(admin_client, a, 1, "A")
    theirs, _ = seed(admin_client, b, 1, "Z")
    admin_client.post(f"/clients/{a}/invoices/{mine[0]['id']}/fields/confirm", json={"field": "odometer"})
    r = admin_client.post(f"/clients/{a}/invoices/bulk-check", json={"ids": [mine[0]["id"], theirs[0]["id"], str(uuid.uuid4())]}).json()
    assert r["checked"] == 1 and r["skipped"] == 2
    assert next(i for i in admin_client.get(f"/clients/{b}/invoices").json() if i["id"] == theirs[0]["id"])["review_status"] == "needs_review"   # B untouched
    assert admin_client.post(f"/clients/{a}/invoices/bulk-check", json={"ids": []}).status_code == 422
    assert admin_client.post(f"/clients/{a}/invoices/bulk-check", json={"ids": [str(uuid.uuid4()) for _ in range(501)]}).status_code == 422


def test_bulk_delete_removes_invoices_lines_marks_and_flags_only_for_that_client(admin_client, world):
    FakeProvider.reset()
    a, b = world["a"], world["b"]
    flags = setup_flags(admin_client, a)                                          # 8 invoices with flags
    victim = flags[0]["invoice_id"]
    other_b, _ = seed(admin_client, b, 1, "Y")
    before = len(admin_client.get(f"/clients/{a}/invoices").json())
    r = admin_client.post(f"/clients/{a}/invoices/bulk-delete", json={"ids": [victim, other_b[0]["id"]]}).json()
    assert r == {"deleted": 1, "skipped": 1}                                      # client B's invoice is not touched
    assert len(admin_client.get(f"/clients/{a}/invoices").json()) == before - 1
    assert len(admin_client.get(f"/clients/{b}/invoices").json()) == 1
    with client_session(a) as db:
        vid = uuid.UUID(victim)
        assert db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == vid)).all() == []
        assert db.scalars(select(Flag).where(Flag.invoice_id == vid)).all() == [] and db.scalars(select(Flag).where(Flag.related_invoice_id == vid)).all() == []
        assert db.scalars(select(FieldConfidence).where(FieldConfidence.record_id == vid)).all() == []
        assert db.get(Invoice, vid) is None
    assert any(x["detail"].get("count") == 1 for x in admin_client.get(f"/admin/audit-log?client_id={a}&action=delete").json()["rows"])


def test_deleting_invoices_does_not_change_a_report_that_already_exists(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    decide(admin_client, cid, flags, len(flags))
    rep = admin_client.post(f"/clients/{cid}/reports", json={}).json()
    snap = admin_client.get(f"/clients/{cid}/reports/{rep['id']}").json()
    pdf = pdf_text(admin_client.get(f"/clients/{cid}/reports/{rep['id']}/pdf").content)
    ids = list({f["invoice_id"] for f in flags})
    assert admin_client.post(f"/clients/{cid}/invoices/bulk-delete", json={"ids": ids}).json()["deleted"] == len(ids)
    assert {k: v for k, v in admin_client.get(f"/clients/{cid}/reports/{rep['id']}").json().items() if k != "out_of_date"} == \
           {k: v for k, v in snap.items() if k != "out_of_date"}               # the content is frozen; out_of_date is computed from today's decisions
    assert pdf_text(admin_client.get(f"/clients/{cid}/reports/{rep['id']}/pdf").content) == pdf


def test_delete_is_admin_only_and_single_delete_works(admin_client, analyst_client, world):
    cid = world["a"]
    invs, _ = seed(admin_client, cid, 2, "D")
    assert analyst_client.post(f"/clients/{cid}/invoices/bulk-delete", json={"ids": [invs[0]["id"]]}).status_code == 403
    assert analyst_client.delete(f"/clients/{cid}/invoices/{invs[0]['id']}").status_code == 403
    assert analyst_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": [invs[0]["id"]]}).status_code == 200   # but checking is ordinary analyst work
    assert admin_client.delete(f"/clients/{cid}/invoices/{invs[0]['id']}").status_code == 204
    assert admin_client.delete(f"/clients/{cid}/invoices/{invs[0]['id']}").status_code == 404
    assert admin_client.delete(f"/clients/{world['b']}/invoices/{invs[1]['id']}").status_code == 404        # not under another client
    assert len(admin_client.get(f"/clients/{cid}/invoices").json()) == 1


# ---- artifact W1: "checked" must not be set on an invoice whose numbers failed the maths/VIN checks unless someone edits or explicitly confirms
def _upload_bad_total(c, cid, num="BAD-1"):
    script(page_json(inv=num, total="999.00"))            # subtotal 580 + tax 0 != total 999
    c.post(f"/clients/{cid}/uploads", files=[("files", (f"{num}.png", png_bytes(seed=uuid.uuid4().int % 10**7), "image/png"))])
    return next(i for i in c.get(f"/clients/{cid}/invoices").json() if i["invoice_number"] == num)


def test_bulk_check_refuses_an_invoice_whose_maths_failed_and_says_which_field(admin_client, world):
    cid = world["a"]
    inv = _upload_bad_total(admin_client, cid)
    r = admin_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": [inv["id"]]}).json()
    assert r["checked"] == 0 and r["blocked"] == [{"id": inv["id"], "fields": ["total"], "reason": r["blocked"][0]["reason"]}]
    assert "add up" in r["blocked"][0]["reason"] or "equal" in r["blocked"][0]["reason"]
    assert next(i for i in admin_client.get(f"/clients/{cid}/invoices").json() if i["id"] == inv["id"])["review_status"] == "needs_review"


def test_mark_checked_on_failed_maths_needs_an_explicit_confirmation(admin_client, world):
    cid = world["a"]
    inv = _upload_bad_total(admin_client, cid, "BAD-2")
    no = admin_client.post(f"/clients/{cid}/invoices/{inv['id']}/mark-checked")
    assert no.status_code == 409 and "total" in no.json()["detail"]
    ok = admin_client.post(f"/clients/{cid}/invoices/{inv['id']}/mark-checked?confirm_as_printed=true")
    assert ok.status_code == 200 and ok.json()["review_status"] == "reviewed"
    rows = admin_client.get(f"/admin/audit-log?client_id={cid}&action=edit&limit=50").json()["rows"]
    assert any((r.get("detail") or {}).get("confirmed_as_printed") for r in rows)


def test_correcting_the_failed_field_lets_the_invoice_be_checked(admin_client, world):
    cid = world["a"]
    inv = _upload_bad_total(admin_client, cid, "BAD-3")
    assert admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "total", "value": "580.00"}).status_code == 200
    r = admin_client.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": [inv["id"]]}).json()
    assert r["checked"] == 1 and "blocked" not in r


# ---- artifact W4: correcting a number refreshes the flags that rest on it; an accepted flag whose inputs changed is marked, never silently kept
def _flags(c, cid):
    return c.get(f"/clients/{cid}/flags").json()["flags"]


def test_correcting_a_field_refreshes_the_open_flags_on_that_invoice(admin_client, world):
    cid = world["a"]
    inv = _upload_bad_total(admin_client, cid, "EDIT-1")
    admin_client.post(f"/clients/{cid}/run-flags")
    assert [f["type"] for f in _flags(admin_client, cid) if f["invoice_number"] == "EDIT-1"] == ["math_error"]
    assert admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "total", "value": "580.00"}).status_code == 200
    assert [f for f in _flags(admin_client, cid) if f["invoice_number"] == "EDIT-1"] == []       # no manual re-run needed


def test_an_accepted_flag_whose_inputs_changed_is_marked_and_blocks_a_report(admin_client, world):
    cid = world["a"]
    inv = _upload_bad_total(admin_client, cid, "EDIT-2")
    admin_client.post(f"/clients/{cid}/run-flags")
    f = next(f for f in _flags(admin_client, cid) if f["invoice_number"] == "EDIT-2")
    assert admin_client.post(f"/clients/{cid}/flags/{f['id']}/accept", json={"extraction_checked": True}).status_code == 200
    admin_client.patch(f"/clients/{cid}/invoices/{inv['id']}/fields", json={"field": "total", "value": "580.00"})   # the number the flag rested on is corrected
    now = next(x for x in _flags(admin_client, cid) if x["id"] == f["id"])
    assert now["status"] == "accepted" and now["evidence"].get("no_longer_applies") is True
    r = admin_client.post(f"/clients/{cid}/reports", json={})
    assert r.status_code == 409 and "corrected after" in r.json()["detail"]
