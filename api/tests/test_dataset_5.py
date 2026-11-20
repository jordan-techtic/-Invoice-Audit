"""Five invoices from synthetic_dataset_v1, end to end through the HTTP API, with the dataset's documents loaded through Settings.

INV-00022, INV-00059 (live invoice 37911), INV-00102 are three invoices for truck T-1026, so they give the odometer history;
INV-00088 and INV-00144 are the planted repeat repair on B-2121. The offline fake "model" returns the PRINTED values, in two variants:
  clean     what is printed
  misread   what a model gets wrong on photos: a VIN character, the last digit of an odometer, a digit of a unit number
Skipped when the dataset is not on this machine (set DATASET_V1_DIR). No AI is called.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import client_session
from app.models import Vehicle
from app.services.extraction.fake import FakeProvider

DATASET = Path(os.environ.get("DATASET_V1_DIR", Path.home() / "Downloads/files/synthetic_dataset_v1_full/synthetic_dataset_v1"))
pytestmark = pytest.mark.skipif(not (DATASET / "truth/invoices.json").exists(), reason="dataset files not on this machine")

IDS = ["INV-00022", "INV-00059", "INV-00102", "INV-00088", "INV-00144"]     # in date order, as they would arrive


def post_file(c, path, data, name="f.csv", **form):
    return c.post(path, files={"file": (name, data, "text/csv")}, data=form)


def sc(v, conf=0.95):
    return {"value": v, "confidence": 0.0 if v is None else conf}


def page(t, misread):
    h, tp = t["header"], t["totals_printed"]
    k = int(hashlib.md5(t["invoice_id"].encode()).hexdigest()[1], 16) % 3
    sub = [tp["parts_subtotal"], tp["labor_subtotal"], tp["total"]][k]            # no Subtotal row is printed: the model picks a footer row
    vin, odo, unit = h["vin"], h["odometer"], h["unit_number"]
    if misread:
        if t["invoice_id"] == "INV-00059":
            vin = vin[:-1] + ("0" if vin[-1] != "0" else "1")                        # one VIN character wrong
        if t["invoice_id"] == "INV-00102":
            odo = int(str(odo)[:-1])                                                 # last digit of the odometer lost
        if t["invoice_id"] == "INV-00088":
            unit = unit[:-2] + "71"                                                  # B-2121 read as B-2171: the fleet has no such truck (B-2122 would be a real one)
    return json.dumps({"is_invoice": True, "page_number": None, "page_count": None, "rotation_degrees": 0,
        "header": {"shop_name": sc(h["shop_name"]), "shop_address": sc(h["shop_address"]), "invoice_number": sc(h["invoice_number"]), "invoice_date": sc(h["invoice_date_as_printed"]),
                   "unit_number": sc(unit), "vin": sc(vin), "odometer": sc(odo), "subtotal": sc(sub), "tax": sc(tp["tax"]), "total": sc(tp["total"])},
        "lines": [{"description": sc(l["description"]), "part_number": sc(l["part_number"]), "qty": sc(l["quantity"]), "parts_price": sc(l["unit_price"]), "labour_hours": sc(l["labor_hours"]),
                   "labour_rate": sc(l["labor_rate"]), "line_total": sc(l["line_total_printed"])} for l in t["line_items"]]})


@pytest.fixture(params=[False, True], ids=["clean_reads", "misreads"])
def run(request, admin_client, world):
    c, cid = admin_client, world["a"]
    truth = {t["invoice_id"]: t for t in json.loads((DATASET / "truth/invoices.json").read_text())}
    th = post_file(c, f"/clients/{cid}/settings/import-thresholds", (DATASET / "master/thresholds_and_rules.json").read_bytes(), "thresholds_and_rules.json")
    assert c.patch(f"/clients/{cid}", json={"settings": th.json()["settings"]}).status_code == 200
    for path, f, kw in (("warranty-rules/import", "warranty_rules.csv", {"mode": "replace"}), ("vehicles/import", "vehicles.csv", {}), ("benchmarks/import-jobs", "jobs_vmrs.csv", {})):
        assert post_file(c, f"/clients/{cid}/{path}", (DATASET / "master" / f).read_bytes(), f, **kw).status_code == 200
    FakeProvider.reset()
    for iid in IDS:
        t = truth[iid]
        f = DATASET / t["documents"][0]["document"]
        FakeProvider.responder = lambda _img, js=page(t, request.param): js
        r = c.post(f"/clients/{cid}/uploads", files={"files": (f.name, f.read_bytes(), "application/pdf" if f.suffix == ".pdf" else "image/jpeg")})
        assert r.status_code == 201 and r.json()[0]["ok"], r.text
    invs = {t["header"]["invoice_number"]: i for i in c.get(f"/clients/{cid}/invoices").json() for t in [truth[x] for x in IDS] if i["invoice_number"] == t["header"]["invoice_number"]}
    num = {iid: truth[iid]["header"]["invoice_number"] for iid in IDS}
    head = lambda iid: c.get(f"/clients/{cid}/invoices/{invs[num[iid]]['id']}").json()["header"]
    assert c.post(f"/clients/{cid}/run-flags").status_code == 202
    return {"misread": request.param, "c": c, "cid": cid, "head": head, "flags": c.get(f"/clients/{cid}/flags").json()["flags"], "num": num, "truth": truth}


def test_the_misreads_are_caught_and_the_clean_reads_raise_no_false_alarm(run):
    h = run["head"]
    if run["misread"]:
        assert h("INV-00059")["vin"]["needs_review"] and "check digit" in h("INV-00059")["vin"]["note"]          # one wrong VIN character
        assert h("INV-00102")["odometer"]["needs_review"] and "other invoices" in h("INV-00102")["odometer"]["note"]   # odometer goes backwards for T-1026
        assert h("INV-00088")["unit_number"]["needs_review"] and "vehicle list" in h("INV-00088")["unit_number"]["note"]   # B-2171 is not in the fleet
    else:
        for iid in IDS:
            for f in ("unit_number", "odometer", "vin", "invoice_number"):
                assert not h(iid)[f]["needs_review"], (iid, f)


def test_a_misread_vin_does_not_become_the_trucks_identity(run):
    with client_session(run["cid"]) as db:
        t1026 = db.scalar(select(Vehicle).where(Vehicle.unit_number == "T-1026"))
        assert t1026.vin == run["truth"]["INV-00059"]["header"]["vin"]       # still the fleet list's VIN, whatever the model read


def test_the_dot_inspection_and_the_repeat_repair_are_found_and_nothing_else(run):
    if run["misread"]:
        pytest.skip("with a misread unit the repeat pair is deliberately not joined")
    found = {(f["invoice_number"], f["type"]) for f in run["flags"]}
    t = run["truth"]
    assert (t["INV-00022"]["header"]["invoice_number"], "labour_over_benchmark") in found                          # the planted $259 annual-inspection overbilling
    assert any(n == t["INV-00144"]["header"]["invoice_number"] and ty in ("repeat_repair", "warranty_eligible") for n, ty in found)
    assert not [f for f in run["flags"] if f["type"] == "math_error"]                                              # no footer-row subtotal turns into a maths flag
    assert len(run["flags"]) == 2


def test_a_review_mark_on_a_misread_blocks_nothing_it_should_not(run):
    c, cid = run["c"], run["cid"]
    ids = [i["id"] for i in c.get(f"/clients/{cid}/invoices").json()]
    r = c.post(f"/clients/{cid}/invoices/bulk-check", json={"ids": ids}).json()
    assert r["checked"] == 4 and [b["fields"] for b in r["blocked"]] == [["vin"]] if run["misread"] else r["checked"] == 5 and "blocked" not in r
