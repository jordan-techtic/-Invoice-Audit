"""10 documents from synthetic_dataset_v1: 5 clean PDFs and 5 that are not clean (scans and photos).

The reported problem: a VIN on a clean invoice was asked about every time. gpt-4o misreads look-alike characters (S/5, Z/2, B/8) even on a clean
PDF; the check digit catches most of them, so the VIN is sent to review. A clean PDF carries its text, so the exact VIN can be read from there.
Skipped when the dataset is not on this machine (set DATASET_V1_DIR). No AI is called.
"""
import json
import os
import uuid
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from app.services.extraction.fake import FakeProvider
from app.services.normalize import vin_check_digit_ok

DATASET = Path(os.environ.get("DATASET_V1_DIR", Path.home() / "Downloads/files/synthetic_dataset_v1_full/synthetic_dataset_v1"))
pytestmark = pytest.mark.skipif(not (DATASET / "truth/invoices.json").exists(), reason="dataset files not on this machine")

LOOKALIKE = {"S": "5", "5": "S", "Z": "2", "2": "Z", "B": "8", "8": "B", "G": "6", "6": "G", "D": "0", "0": "D"}


def misread(vin: str) -> str:
    """One look-alike character wrong, chosen so the check digit no longer passes (what gpt-4o actually does)."""
    for i, ch in enumerate(vin):
        if i != 8 and ch in LOOKALIKE:
            bad = vin[:i] + LOOKALIKE[ch] + vin[i + 1:]
            if not vin_check_digit_ok(bad):
                return bad
    return vin[:3] + ("1" if vin[3] != "1" else "2") + vin[4:]


def pick():
    truth = json.loads((DATASET / "truth/invoices.json").read_text())
    docs = {d["document"]: d for d in json.loads((DATASET / "truth/documents.json").read_text())}
    single = [t for t in truth if "multi" not in t["documents"][0]["document"] and len(docs[t["documents"][0]["document"]]["pages"]) == 1]
    clean = [t for t in single if t["format"] == "clean"][:5]
    messy = ([t for t in single if t["format"] == "scanned" and t["documents"][0]["document"].endswith(".pdf")][:2]
             + [t for t in single if t["format"] == "scanned" and t["documents"][0]["document"].endswith(".jpg")][:1]
             + [t for t in single if t["format"] == "photo"][:2])
    assert len(clean) == 5 and len(messy) == 5
    return clean, messy


def _vins_in_text_layer(path: str) -> list[str]:
    """Runs in its own process: pdfium is not thread-safe, so parallel reading must use processes, not threads."""
    from app.services import textlayer

    return textlayer.valid_vins("\n".join(textlayer.page_texts(Path(path).read_bytes())))


def test_the_exact_vin_is_found_in_the_text_of_every_clean_pdf_and_in_no_scan_or_photo():
    clean, messy = pick()
    paths = [str(DATASET / t["documents"][0]["document"]) for t in clean + messy]
    with ProcessPoolExecutor(max_workers=10, mp_context=multiprocessing.get_context("spawn")) as pool:   # the 10 documents are independent: read them in parallel
        got = list(pool.map(_vins_in_text_layer, paths))
    assert got[:5] == [[t["header"]["vin"]] for t in clean]
    assert got[5:] == [[]] * 5


def sc(v, conf=0.95):
    return {"value": v, "confidence": 0.0 if v is None else conf}


def page(t, vin):
    h, tp = t["header"], t["totals_printed"]
    return json.dumps({"is_invoice": True, "page_number": None, "page_count": None, "rotation_degrees": 0,
        "header": {"shop_name": sc(h["shop_name"]), "shop_address": sc(h["shop_address"]), "invoice_number": sc(h["invoice_number"]), "invoice_date": sc(h["invoice_date_as_printed"]),
                   "unit_number": sc(h["unit_number"]), "vin": sc(vin), "odometer": sc(h["odometer"]), "subtotal": sc(None), "tax": sc(tp["tax"]), "total": sc(tp["total"])},
        "lines": [{"description": sc(l["description"]), "part_number": sc(l["part_number"]), "qty": sc(l["quantity"]), "parts_price": sc(l["unit_price"]), "labour_hours": sc(l["labor_hours"]),
                   "labour_rate": sc(l["labor_rate"]), "line_total": sc(l["line_total_printed"])} for l in t["line_items"]]})


@pytest.fixture(params=[False, True], ids=["model_reads_vin_correctly", "model_misreads_a_look_alike_character"])
def run(request, admin_client, world):
    c, cid = admin_client, world["a"]
    clean, messy = pick()
    FakeProvider.reset()
    for t in clean + messy:
        f = DATASET / t["documents"][0]["document"]
        vin = misread(t["header"]["vin"]) if request.param else t["header"]["vin"]
        FakeProvider.responder = lambda _img, js=page(t, vin): js
        r = c.post(f"/clients/{cid}/uploads", files={"files": (f.name, f.read_bytes(), "application/pdf" if f.suffix == ".pdf" else "image/jpeg")})
        assert r.status_code == 201 and r.json()[0]["ok"], r.text
    by_num = {i["invoice_number"]: i for i in c.get(f"/clients/{cid}/invoices").json()}
    vin = lambda t: c.get(f"/clients/{cid}/invoices/{by_num[t['header']['invoice_number']]['id']}").json()["header"]["vin"]
    return {"misread": request.param, "clean": clean, "messy": messy, "vin": vin}


def test_a_clean_invoice_never_asks_about_its_vin(run):
    for t in run["clean"]:
        v = run["vin"](t)
        assert v["value"] == t["header"]["vin"] and not v["needs_review"], (t["invoice_id"], v)      # right whether or not the model misread it


def test_a_scan_or_photo_still_asks_when_the_vin_was_misread(run):
    for t in run["messy"]:
        v = run["vin"](t)
        if run["misread"]:
            assert v["needs_review"] and "check digit" in v["note"], (t["invoice_id"], v)             # no text to check against: the person must look
        else:
            assert v["value"] == t["header"]["vin"] and not v["needs_review"], (t["invoice_id"], v)
