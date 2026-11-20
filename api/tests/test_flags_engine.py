import io
import json
from datetime import date
from decimal import Decimal as D

from sqlalchemy import select

from app.db import client_session
from app.flags.engine import run_flag_engine
from app.models import Flag, FlagExplanationCache, FlagStatus, Invoice, InvoiceLine, LabourBenchmark
from app.services.extraction.fake import FakeProvider


def add_invoice(db, num, dt, unit="T-1", shop="Acme Truck", odo=None, lines=(), total=None, subtotal=None, tax=D("0")):
    inv = Invoice(invoice_number=num, invoice_date=dt, unit_number=unit, shop_name_raw=shop, odometer=odo,
                  subtotal=subtotal if subtotal is not None else total, tax=tax, total=total)
    db.add(inv)
    db.flush()
    for n, (desc, code, hours, rate, price, tot) in enumerate(lines, start=1):
        db.add(InvoiceLine(invoice_id=inv.id, line_no=n, description=desc, vmrs_code=code, labour_hours=hours, labour_rate=rate,
                           parts_price=price, line_total=tot, qty=D(1) if price else None))
    db.flush()
    return inv


def seed_world(cid):
    """Six water-pump jobs at ~2h (benchmark 2.0) plus one billed at 4h, repeated within 30 days on the same unit."""
    with client_session(cid) as db:
        for i in range(6):
            add_invoice(db, f"P{i}", date(2025, 1 + i, 5), unit=f"U{i}", lines=[("R&R water pump", "042-001-002", D("2.0"), D("100"), None, D("200"))], total=D("200"))
        add_invoice(db, "BIG", date(2026, 1, 5), unit="U9", lines=[("R&R water pump", "042-001-002", D("4.0"), D("100"), None, D("400"))], total=D("400"))
        add_invoice(db, "BIG2", date(2026, 2, 1), unit="U9", lines=[("R&R water pump", "042-001-002", D("2.0"), D("100"), None, D("200"))], total=D("200"))
        db.commit()


def test_engine_creates_open_flags_with_reasons_and_is_idempotent(world):
    FakeProvider.reset()
    seed_world(world["a"])
    with client_session(world["a"]) as db:
        s = run_flag_engine(db)
        db.commit()
        flags = db.scalars(select(Flag)).all()
        types = sorted(f.type.value for f in flags)
        assert "labour_over_benchmark" in types and "repeat_repair" in types
        assert all(f.status == FlagStatus.open and f.estimated_dollar_impact > 0 and f.plain_english_reason for f in flags)
        assert all(("ikely" in f.plain_english_reason or "ossible" in f.plain_english_reason) for f in flags)
        lab = next(f for f in flags if f.type.value == "labour_over_benchmark")
        assert lab.estimated_dollar_impact == D("200.00") and lab.severity.value == "medium" and lab.details["benchmark_hours"] == 2.0
        n = len(flags)
        run_flag_engine(db)
        db.commit()
        assert len(db.scalars(select(Flag)).all()) == n   # re-running does not duplicate flags
        assert s["flags"] == n


def test_engine_never_overwrites_an_analyst_decision(world):
    FakeProvider.reset()
    seed_world(world["a"])
    with client_session(world["a"]) as db:
        run_flag_engine(db)
        f = db.scalars(select(Flag)).first()
        f.status, f.analyst_note = FlagStatus.accepted, "confirmed with shop"
        fid = f.id
        db.commit()
        run_flag_engine(db)
        db.commit()
        again = db.get(Flag, fid)
        assert again.status == FlagStatus.accepted and again.analyst_note == "confirmed with shop"


def test_open_flags_that_no_longer_apply_are_removed(world):
    FakeProvider.reset()
    seed_world(world["a"])
    with client_session(world["a"]) as db:
        run_flag_engine(db)
        db.commit()
        assert db.scalars(select(Flag).where(Flag.type == "labour_over_benchmark")).first()
        db.execute(__import__("sqlalchemy").update(InvoiceLine).where(InvoiceLine.labour_hours == D("4.0")).values(labour_hours=D("2.0")))
        db.commit()
        run_flag_engine(db)
        db.commit()
        assert db.scalars(select(Flag).where(Flag.type == "labour_over_benchmark")).first() is None


def test_ai_failure_keeps_flags_with_template_reasons(world):
    FakeProvider.reset()
    FakeProvider.explain_fail = True
    seed_world(world["a"])
    with client_session(world["a"]) as db:
        s = run_flag_engine(db)
        db.commit()
        flags = db.scalars(select(Flag)).all()
        assert flags and all(f.plain_english_reason and f.ai_score is None for f in flags)
        assert any("standard wording" in n for n in s["notes"])
    FakeProvider.reset()


def test_ai_wording_guardrail_replaces_accusations(world):
    FakeProvider.reset()
    seed_world(world["a"])
    FakeProvider.explain_scripted = [json.dumps({"items": [{"index": i, "reason": "The shop committed fraud.", "ai_score": 0.9} for i in range(15)]})] * 5
    with client_session(world["a"]) as db:
        run_flag_engine(db)
        db.commit()
        assert all("fraud" not in f.plain_english_reason.lower() for f in db.scalars(select(Flag)))
    FakeProvider.reset()


def test_explanations_are_cached_by_evidence(world):
    FakeProvider.reset()
    seed_world(world["a"])
    FakeProvider.explain_scripted = [json.dumps({"items": [{"index": i, "reason": "This is a likely issue worth a look.", "ai_score": 0.7} for i in range(15)]})] * 5
    with client_session(world["a"]) as db:
        run_flag_engine(db)
        db.commit()
        calls = FakeProvider.explain_calls
        assert calls >= 1 and db.scalars(select(FlagExplanationCache)).first()
        run_flag_engine(db)
        db.commit()
        assert FakeProvider.explain_calls == calls  # second run needed no AI calls
    FakeProvider.reset()


def test_licensed_benchmark_overrides_computed_one(world):
    FakeProvider.reset()
    seed_world(world["a"])
    with client_session(world["a"]) as db:
        db.add(LabourBenchmark(vmrs_code="042-001-002", benchmark_hours=D("1.0"), source="licensed:import"))
        db.commit()
        run_flag_engine(db)
        db.commit()
        # with a 1.0h benchmark every 2.0h water pump job is now 100% over
        assert len(db.scalars(select(Flag).where(Flag.type == "labour_over_benchmark")).all()) >= 7


# ---------------------------------------------------------------- API + isolation
def test_run_flags_endpoint_and_listing(admin_client, world):
    FakeProvider.reset()
    seed_world(world["a"])
    r = admin_client.post(f"/clients/{world['a']}/run-flags")
    assert r.status_code == 202
    run = admin_client.get(f"/clients/{world['a']}/flag-runs/{r.json()['job_id']}").json()
    assert run["status"] == "done" and run["summary"]["flags"] >= 2
    body = admin_client.get(f"/clients/{world['a']}/flags").json()
    impacts = [f["impact"] for f in body["flags"]]
    assert impacts == sorted(impacts, reverse=True) and body["total_possible_recoverable"] > 0
    only = admin_client.get(f"/clients/{world['a']}/flags?type=repeat_repair&status=open").json()
    assert only["count"] >= 1 and all(f["type"] == "repeat_repair" for f in only["flags"])
    asc = admin_client.get(f"/clients/{world['a']}/flags?sort=impact_asc").json()["flags"]
    assert [f["impact"] for f in asc] == sorted(f["impact"] for f in asc)
    assert admin_client.get(f"/clients/{world['a']}/flags?type=nope").status_code == 422


def test_flags_never_cross_clients(admin_client, analyst_client, world):
    FakeProvider.reset()
    seed_world(world["a"])
    seed_world(world["b"])
    admin_client.post(f"/clients/{world['a']}/run-flags")
    # client B has invoices but has not run checks: it must have no flags, and A's flags must not leak into it
    assert admin_client.get(f"/clients/{world['b']}/flags").json()["count"] == 0
    with client_session(world["b"]) as db:
        assert db.scalars(select(Flag)).all() == []
    # running B creates only B's flags, on B's invoices
    admin_client.post(f"/clients/{world['b']}/run-flags")
    with client_session(world["b"]) as db:
        b_invoices = {i.id for i in db.scalars(select(Invoice))}
        assert db.scalars(select(Flag)).all() and all(f.invoice_id in b_invoices for f in db.scalars(select(Flag)))
    # an analyst of A can't touch any of B's flag or reference endpoints
    for method, path, kw in [("get", "flags", {}), ("post", "run-flags", {}), ("get", "warranty-rules", {}), ("get", "benchmarks", {}),
                             ("post", "warranty-rules", {"json": {"vmrs_code": "031-001-001", "component": "x", "months": 1}}),
                             ("post", "benchmarks/import", {"files": {"file": ("b.csv", b"vmrs_code,benchmark_hours\n", "text/csv")}})]:
        assert getattr(analyst_client, method)(f"/clients/{world['b']}/{path}", **kw).status_code == 404, path
    assert analyst_client.get(f"/clients/{world['a']}/flags").status_code == 200


def test_warranty_rules_admin_can_edit_analyst_cannot(admin_client, analyst_client, world):
    cid = world["a"]
    fresh = admin_client.post("/clients", json={"name": "Empty Test Fleet"}).json()["id"]
    assert admin_client.get(f"/clients/{fresh}/warranty-rules").json() == []   # new clients start empty: terms come from an import, not from us
    rules = admin_client.get(f"/clients/{cid}/warranty-rules").json()
    assert any(r["component"] == "Alternator A" and r["months"] == 12 and r["miles"] == 100000 for r in rules)
    alt = next(r for r in rules if r["component"].startswith("Alternator"))
    assert admin_client.put(f"/clients/{cid}/warranty-rules/{alt['id']}", json={"months": 18}).json()["months"] == 18
    assert analyst_client.put(f"/clients/{cid}/warranty-rules/{alt['id']}", json={"months": 1}).status_code == 403
    assert analyst_client.get(f"/clients/{cid}/warranty-rules").status_code == 200
    assert admin_client.post(f"/clients/{cid}/warranty-rules", json={"vmrs_code": "031-001-001", "component": "dup", "months": 3}).status_code == 409
    assert admin_client.post(f"/clients/{cid}/warranty-rules", json={"vmrs_code": "999-999-999", "component": "x", "months": 3}).status_code == 422
    assert admin_client.delete(f"/clients/{cid}/warranty-rules/{alt['id']}").status_code == 204


def test_benchmark_csv_import(admin_client, world):
    cid = world["a"]
    up = lambda text: admin_client.post(f"/clients/{cid}/benchmarks/import", files={"file": ("b.csv", text.encode(), "text/csv")})
    assert "vmrs_code and benchmark_hours" in up("a,b\n1,2\n").json()["detail"]
    assert "Row 2" in up("vmrs_code,benchmark_hours\n999-9,2\n").json()["detail"]
    assert "isn't a number" in up("vmrs_code,benchmark_hours\n031-001-001,abc\n").json()["detail"]
    ok = up("vmrs_code,benchmark_hours\n031-001-001,2.5\n042-001-002,3\n")
    assert ok.json() == {"imported": 2}
    rows = {b["vmrs_code"]: b for b in admin_client.get(f"/clients/{cid}/benchmarks").json()}
    assert rows["031-001-001"]["hours"] == 2.5 and rows["031-001-001"]["source"] == "licensed:import"
    assert up("vmrs_code,benchmark_hours\n031-001-001,9\n").json() == {"imported": 1}   # re-import replaces


# ---- artifact W2: "check extraction first" must not depend on the invoice still being un-checked
def _math_flag_on_a_line(world, score, field="line_total", needs_review=False):
    from app.models import FieldConfidence

    with client_session(world["a"]) as db:
        inv = add_invoice(db, "X1", date(2026, 1, 5), unit="U1", lines=[("R&R water pump", "042-001-002", D("2.0"), D("100"), D("70"), D("300"))], total=D("300"))
        line = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).first()          # parts 70 + labour 200 = 270, printed 300
        db.add(FieldConfidence(record_type="line", record_id=line.id, field=field, score=score, needs_review=needs_review))
        db.commit()
    with client_session(world["a"]) as db:
        run_flag_engine(db)
        db.commit()
        return [f for f in db.scalars(select(Flag)) if f.type.value == "math_error" and f.line_id is not None][0].details.get("extraction_uncertain")


def test_a_low_score_still_marks_the_flag_after_the_invoice_was_marked_checked(world):
    assert _math_flag_on_a_line(world, score=0.6, needs_review=False) == ["line_total"]      # needs_review was cleared by "mark as checked"; the score was not


def test_a_field_the_analyst_edited_is_no_longer_uncertain(world):
    assert not _math_flag_on_a_line(world, score=1.0, needs_review=False)


def test_a_field_that_is_simply_not_on_the_invoice_is_not_uncertain(world):
    assert not _math_flag_on_a_line(world, score=0.0, field="qty", needs_review=False)


# ---- artifact L7: two flags with identical evidence (a re-billed copy, the same job on two invoices) must not crash the whole run
def test_two_flags_with_identical_evidence_do_not_crash_the_run(world):
    FakeProvider.reset()
    FakeProvider.explain_scripted = [json.dumps({"items": [{"index": i, "reason": "This is a likely billing issue worth a look.", "ai_score": 0.7} for i in range(15)]})] * 5
    with client_session(world["a"]) as db:
        for num, dt, unit in (("A1", date(2026, 1, 5), "U1"), ("A2", date(2026, 2, 9), "U2")):   # two different jobs, same numbers: identical evidence, not duplicates
            add_invoice(db, num, dt, unit=unit, lines=[("R&R water pump", "042-001-002", D("2.0"), D("100"), None, D("100"))], total=D("100"))
        db.commit()
    with client_session(world["a"]) as db:
        summary = run_flag_engine(db)
        db.commit()
        flags = [f for f in db.scalars(select(Flag)) if f.type.value == "math_error"]
        assert len(flags) == 2 and all(f.plain_english_reason.startswith("This is a likely billing issue") for f in flags)
        assert summary["flags"] >= 2
