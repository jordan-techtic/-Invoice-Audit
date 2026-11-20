"""End to end on 20 hand-picked invoices from synthetic_dataset_v1, through the HTTP API, with the dataset's own documents loaded through Settings.

 documents -> Settings : thresholds_and_rules.json, warranty_rules.csv, vehicles.csv, jobs_vmrs.csv (the same imports an admin uses)
 20 invoices -> upload : the offline fake "model" returns the dataset's PRINTED values, plus the defect seen on the live site (the model fills
                         `subtotal` from the Parts, Labor or TOTAL DUE footer row, because these invoices have no Subtotal row)
 -> run checks -> review as the web app does -> accept -> report and PDF

The 20: the 8 invoices from the live test that exist in the dataset (37911, CO-51967, 43-704, 37890, 37926, 44-198, 48-809, INV0024793),
a planted duplicate pair, a repeat pair, a warranty pair, a planted maths error, and one invoice per remaining layout.
Skipped when the dataset is not on this machine (set DATASET_V1_DIR to its synthetic_dataset_v1 folder). No AI is called.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction.fake import FakeProvider

DATASET = Path(os.environ.get("DATASET_V1_DIR", Path.home() / "Downloads/files/synthetic_dataset_v1_full/synthetic_dataset_v1"))
pytestmark = pytest.mark.skipif(not (DATASET / "truth/invoices.json").exists(), reason="dataset files not on this machine")

IDS = ["INV-00059", "INV-00010", "INV-00018", "INV-00022", "INV-00102", "INV-00058", "INV-00060", "INV-00047",   # live-test invoices
       "INV-00131", "INV-00136",                                                                                  # planted duplicate (same number, date shifted)
       "INV-00088", "INV-00144",                                                                                  # planted repeat repair
       "INV-00038", "INV-00211",                                                                                  # planted warranty case
       "INV-00027",                                                                                               # planted maths error (an over-billed parts line)
       "INV-00001", "INV-00019", "INV-00013", "INV-00011", "INV-00004"]                                           # one per remaining layout
PLANTED_MATHS = {"INV-00027"}


def post_file(c, path, data, name="f.csv", **form):
    return c.post(path, files={"file": (name, data, "text/csv")}, data=form)


def sc(v, conf=0.95):
    return {"value": v, "confidence": 0.0 if v is None else conf}


def page(t, subtotal_mode):
    h, tp = t["header"], t["totals_printed"]
    k = int(hashlib.md5(t["invoice_id"].encode()).hexdigest()[1], 16) % 3
    sub = {"footer_row": [tp["parts_subtotal"], tp["labor_subtotal"], tp["total"]][k], "null": None}[subtotal_mode]
    return json.dumps({"is_invoice": True, "page_number": None, "page_count": None, "rotation_degrees": 0,
        "header": {"shop_name": sc(h["shop_name"]), "shop_address": sc(h["shop_address"]), "invoice_number": sc(h["invoice_number"]), "invoice_date": sc(h["invoice_date_as_printed"]),
                   "unit_number": sc(h["unit_number"]), "vin": sc(h["vin"]), "odometer": sc(h["odometer"]), "subtotal": sc(sub), "tax": sc(tp["tax"]), "total": sc(tp["total"])},
        "lines": [{"description": sc(l["description"]), "part_number": sc(l["part_number"]), "qty": sc(l["quantity"]), "parts_price": sc(l["unit_price"]), "labour_hours": sc(l["labor_hours"]),
                   "labour_rate": sc(l["labor_rate"]), "line_total": sc(l["line_total_printed"])} for l in t["line_items"]]})


@pytest.fixture(params=["footer_row", "null"], ids=["model_fills_subtotal_from_a_footer_row", "model_leaves_subtotal_null"])
def run(request, admin_client, world):
    """Load the documents, upload the 20 invoices, run the checks. Returns what the tests look at."""
    c, cid = admin_client, world["a"]
    truth = {t["invoice_id"]: t for t in json.loads((DATASET / "truth/invoices.json").read_text())}
    out = {"c": c, "cid": cid, "truth": truth}

    th = post_file(c, f"/clients/{cid}/settings/import-thresholds", (DATASET / "master/thresholds_and_rules.json").read_bytes(), "thresholds_and_rules.json")
    assert th.status_code == 200, th.text
    assert c.patch(f"/clients/{cid}", json={"settings": th.json()["settings"]}).status_code == 200
    out["settings"] = c.get(f"/clients/{cid}").json()["settings"]
    assert post_file(c, f"/clients/{cid}/warranty-rules/import", (DATASET / "master/warranty_rules.csv").read_bytes(), "warranty_rules.csv", mode="replace").status_code == 200
    assert post_file(c, f"/clients/{cid}/vehicles/import", (DATASET / "master/vehicles.csv").read_bytes(), "vehicles.csv").status_code == 200
    assert post_file(c, f"/clients/{cid}/benchmarks/import-jobs", (DATASET / "master/jobs_vmrs.csv").read_bytes(), "jobs_vmrs.csv").status_code == 200

    FakeProvider.reset()
    for iid in IDS:
        t = truth[iid]
        f = DATASET / t["documents"][0]["document"]
        FakeProvider.responder = lambda _img, js=page(t, request.param): js
        r = c.post(f"/clients/{cid}/uploads", files={"files": (f.name, f.read_bytes(), "application/pdf" if f.suffix == ".pdf" else "image/jpeg")})
        assert r.status_code == 201 and r.json()[0]["ok"], r.text
    out["invoices"] = c.get(f"/clients/{cid}/invoices").json()
    assert c.post(f"/clients/{cid}/run-flags").status_code == 202
    out["flags"] = c.get(f"/clients/{cid}/flags").json()
    out["key"] = {(t["header"]["invoice_number"], t["header"]["shop_name"]): k for k, t in truth.items()}
    out["key_of"] = lambda f: out["key"].get((f["invoice_number"], f["shop"]))
    return out


def test_the_documents_load_through_settings(run):
    s = run["settings"]
    assert (s["labour_over_benchmark_pct"], s["repeat_repair_days"], s["repeat_repair_miles"], s["parts_outlier_pct"], s["parts_min_samples"], s["duplicate_window_days"]) == (20, 90, 15000, 50, 5, 10)
    assert len(run["invoices"]) == 20


def test_dates_in_every_layout_are_read(run):
    assert all(i["invoice_date"] for i in run["invoices"])          # 2025/06/06, 01-May-2025, 05-10-25, May 09, 2025 ... all parse


def test_no_false_maths_flags_whether_or_not_the_model_invents_a_subtotal(run):
    maths = [f for f in run["flags"]["flags"] if f["type"] == "math_error"]
    wrong = [(run["key_of"](f), f["impact"]) for f in maths if run["key_of"](f) not in PLANTED_MATHS]
    assert wrong == []        # before the fix this was 18 false flags (about $2,900) on these 20 invoices


def test_the_planted_duplicate_repeat_and_warranty_cases_are_found(run):
    found = {}
    for f in run["flags"]["flags"]:
        found.setdefault(run["key_of"](f), set()).add(f["type"])
    assert "duplicate" in found.get("INV-00136", set()) | found.get("INV-00131", set())
    assert found.get("INV-00144", set()) & {"repeat_repair", "warranty_eligible"}
    assert "warranty_eligible" in found.get("INV-00211", set()) | found.get("INV-00038", set())


def test_warranty_flag_claims_the_parts_only_when_the_rule_covers_parts_only(run):
    f = next(f for f in run["flags"]["flags"] if f["type"] == "warranty_eligible" and run["key_of"](f) == "INV-00211")
    assert f["evidence"]["covers"] == "parts" and f["impact"] < run["truth"]["INV-00211"]["totals_printed"]["total"]


def _check_all(c, cid, invoices):
    """Bulk-check as the web app does. The one invoice with a genuinely wrong printed line total is held back, then confirmed as printed."""
    r = c.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": [i["id"] for i in invoices]}).json()
    held = {i["id"]: i["invoice_number"] for i in invoices if i["id"] in {b["id"] for b in r.get("blocked", [])}}
    return r, held


def test_the_review_step_blocks_only_the_invoice_whose_own_numbers_are_wrong(run):
    c, cid = run["c"], run["cid"]
    r, held = _check_all(c, cid, run["invoices"])
    assert r["checked"] == 19 and list(held.values()) == ["INV0039187"]          # INV-00027, the planted maths error: its line total really does not add up
    assert r["blocked"][0]["fields"] == ["line_total"]
    bad = next(i for i in run["invoices"] if i["invoice_number"] == "INV0039187")
    assert c.post(f"/clients/{cid}/invoices/{bad['id']}/mark-checked").status_code == 409       # not silently
    assert c.post(f"/clients/{cid}/invoices/{bad['id']}/mark-checked?confirm_as_printed=true").status_code == 200
    assert {i["review_status"] for i in c.get(f"/clients/{cid}/invoices").json()} == {"reviewed"}


def test_the_report_matches_the_decisions_and_is_safe_to_hand_over(run):
    c, cid = run["c"], run["cid"]
    _, held = _check_all(c, cid, run["invoices"])
    for iid in held:
        assert c.post(f"/clients/{cid}/invoices/{iid}/mark-checked?confirm_as_printed=true").status_code == 200
    assert c.post(f"/clients/{cid}/run-flags").status_code == 202
    flags = c.get(f"/clients/{cid}/flags").json()["flags"]
    assert flags
    c.post(f"/clients/{cid}/flags/bulk", json={"ids": [f["id"] for f in flags], "action": "accept", "extraction_checked": True})
    rep = c.post(f"/clients/{cid}/reports", json={})
    assert rep.status_code == 201, rep.text
    snap = c.get(f"/clients/{cid}/reports/{rep.json()['id']}").json()
    assert snap["cover"]["invoices_reviewed"] == 20 and snap["out_of_date"] is False
    assert snap["summary"]["pct_of_spend"] < 25           # the live site reported 45% of spend, all of it false maths flags
    top = max(flags, key=lambda f: f["impact"])
    c.post(f"/clients/{cid}/flags/{top['id']}/dismiss", json={"reason": "not_real_issue"})
    assert c.get(f"/clients/{cid}/reports/{rep.json()['id']}").json()["out_of_date"] is True
    v2 = c.post(f"/clients/{cid}/reports", json={})
    assert v2.status_code == 201
    assert TestClient(app).get(f"/public/reports/{rep.json()['share_url'].rsplit('/r/', 1)[1]}").status_code == 410     # v1's link is off
    pdf = c.get(f"/clients/{cid}/reports/{v2.json()['id']}/pdf").content
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.pdf"
        p.write_bytes(pdf)
        text = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True).stdout
    assert "None" not in text and re.search(r"reviewed by an analyst", text.replace("\n", " "))
