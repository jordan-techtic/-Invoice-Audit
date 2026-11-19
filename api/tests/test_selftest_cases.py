"""Self-test cases 1-5 and 8 on the synthetic invoices. Needs /synthetic/out (mounted by `make test-selftest`/demo); skipped if absent.

Where a case needs a real model to read pixels it is split in two: the part that is real here (preprocessing, splitting,
status handling) and the part that uses the OFFLINE ORACLE (replays the answer key). The oracle never looks at an image."""

import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageFilter
from sqlalchemy import select

from app.db import client_session
from app.models import Invoice, Upload, UploadSource
from app.services.extraction.fake import FakeProvider
from app.services.ingest import ingest_file
from app.services.preprocess import _deskew_angle, prepare_page, render_pages, sniff_type
from eval.oracle import pages_for_file
from eval.run_eval import HEADER, same

from .helpers import page_json, pdf_bytes, png_bytes, script

SYN = Path("/synthetic/out")
pytestmark = pytest.mark.skipif(not (SYN / "answer_key.json").exists(), reason="synthetic set not mounted at /synthetic/out")


@pytest.fixture(scope="module")
def key():
    return json.loads((SYN / "answer_key.json").read_text())


@pytest.fixture(scope="module")
def meta():
    p = SYN / "generation_meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


def pick(key, kind, n=1, skip=0):
    out = [f for f in key["files"] if f["kind"] == kind and not f.get("exact_duplicate_of") and len(f["invoices"]) == 1]
    return out[skip: skip + n]


def read_file(cid, entry, seed=1):
    FakeProvider.reset()
    it = iter(pages_for_file(entry, random.Random(seed)))
    FakeProvider.responder = lambda _img: next(it)
    with client_session(cid) as db:
        db.info["user_id"] = None
        up = ingest_file(db, filename=Path(entry["file"]).name, data=(SYN / entry["file"]).read_bytes(), source=UploadSource.web)
        invs = db.scalars(select(Invoice).where(Invoice.source_upload_id == up.id).order_by(Invoice.page_start)).all()
        return up, invs


def test_case_01_clean_pdf_skewed_scan_and_phone_photo_are_extracted(world, key):
    """Pipeline on one clean PDF, one skewed scan, one phone photo (oracle reads; preprocessing is real, see next test)."""
    res = {}
    for kind in ("clean_pdf", "skewed_scan", "phone_photo"):
        entry = pick(key, kind)[0]
        up, invs = read_file(world["a"], entry)
        assert up.status.value in ("done", "needs_review") and len(invs) == 1 and up.page_count >= 1
        want = entry["invoices"][0]["header"]
        ok = sum(same(f, invs[0].shop_name_raw if f == "shop_name" else getattr(invs[0], f), want.get(f)) for f in HEADER)
        assert ok >= 8
        res[kind] = f"{ok}/10 header fields"
    assert len(res) == 3


def test_case_01b_preprocessing_really_straightens_skewed_scans_and_opens_every_file_type(key, meta):
    """REAL (no AI): the de-skew angle is compared with the generator's TRUE skew for 30 scans, and every synthetic
    file type renders and re-encodes."""
    import numpy as np

    truth, est = [], []
    for entry in [f for f in key["files"] if f["kind"] == "skewed_scan"][:30]:
        data = (SYN / entry["file"]).read_bytes()
        img = render_pages(data, sniff_type(data))[0]
        est.append(_deskew_angle(np.array(img.convert("L"))))
        truth.append(meta[entry["invoices"][0]["key_id"]]["files"][0]["skew_deg"])
        assert len(prepare_page(img)) > 1000
    truth, est = np.array(truth), np.array(est)
    residual = np.abs(truth - est)          # what is left after rotating by the estimate
    print(f"skew before: mean {np.abs(truth).mean():.2f} deg; after: mean {residual.mean():.2f}, max {residual.max():.2f}")
    assert len(truth) >= 25 and residual.mean() < 0.5 and residual.mean() < np.abs(truth).mean() / 2 and residual.max() < 2.0
    assert np.corrcoef(truth, est)[0, 1] > 0.9
    for kind in ("clean_pdf", "phone_photo", "handwritten", "multi_pdf"):
        e = next(f for f in key["files"] if f["kind"] == kind)
        data = (SYN / e["file"]).read_bytes()
        pages = render_pages(data, sniff_type(data))
        assert pages and Image.open(io.BytesIO(prepare_page(pages[0]))).size[0] > 500


def test_case_01c_heic_is_converted_and_read(world):
    """REAL: a HEIC photo is accepted, converted and goes through the pipeline."""
    import pillow_heif

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.open(io.BytesIO(png_bytes(seed=4242))).convert("RGB").save(buf, "HEIF")
    assert sniff_type(buf.getvalue()) == "heic"
    script(page_json(inv="HEIC-1"))
    with client_session(world["a"]) as db:
        db.info["user_id"] = None
        up = ingest_file(db, filename="IMG_0001.HEIC", data=buf.getvalue(), source=UploadSource.web)
        assert up.status.value in ("done", "needs_review") and up.invoice_count == 1


def test_case_02_multi_invoice_pdfs_are_split_into_the_right_invoices(world, key):
    multi = [f for f in key["files"] if f["kind"] == "multi_pdf"]
    assert len(multi) == 3
    for entry in multi:
        up, invs = read_file(world["a"], entry)
        want = sorted(entry["invoices"], key=lambda i: i["page_start"])
        assert len(invs) == len(want), entry["file"]
        assert [(i.page_start, i.page_end) for i in invs] == [(w["page_start"], w["page_end"]) for w in want]
        assert any(w["page_end"] > w["page_start"] for e in multi for w in e["invoices"])  # includes 2-page invoices


def test_case_03_same_file_twice_is_skipped_and_the_user_is_told(admin_client, world, key):
    entry = pick(key, "clean_pdf", skip=5)[0]
    data = (SYN / entry["file"]).read_bytes()
    FakeProvider.reset()
    it = iter(pages_for_file(entry, random.Random(3)))
    FakeProvider.responder = lambda _img: next(it)
    first = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("first.pdf", data, "application/pdf"))]).json()[0]["upload"]
    second = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("again.pdf", data, "application/pdf"))]).json()[0]["upload"]
    assert second["status"] == "duplicate" and "identical to first.pdf" in second["status_detail"] and second["duplicate_of"] == first["id"]
    # and all 4 exact duplicates planted in the set
    dups = [f for f in key["files"] if f.get("exact_duplicate_of")]
    assert len(dups) == 4
    for d in dups:
        orig = next(f for f in key["files"] if f["file"] == d["exact_duplicate_of"])
        read_file(world["b"], orig)
        with client_session(world["b"]) as db:
            db.info["user_id"] = None
            up = ingest_file(db, filename=Path(d["file"]).name, data=(SYN / d["file"]).read_bytes(), source=UploadSource.web)
            assert up.status.value == "duplicate", d["file"]


def test_case_04_unsupported_or_corrupt_files_give_clear_errors_and_no_crash(admin_client, world):
    cid = world["a"]
    post = lambda name, data, ct="application/octet-stream": admin_client.post(f"/clients/{cid}/uploads", files=[("files", (name, data, ct))])
    r = post("macro.exe", b"MZ\x90\x00" + b"\x00" * 200)
    assert r.status_code == 201 and r.json()[0]["ok"] is False and "isn't a PDF, JPG, PNG or HEIC" in r.json()[0]["error"]
    assert "isn't a PDF" in post("notes.txt", b"just text", "text/plain").json()[0]["error"]
    assert "empty" in post("empty.pdf", b"").json()[0]["error"]
    # looks like a PDF / PNG but is damaged: accepted, then fails with a message the user can act on
    FakeProvider.reset()
    bad_pdf = post("broken.pdf", b"%PDF-1.7\n1 0 obj << /Broken", "application/pdf").json()[0]["upload"]
    assert bad_pdf["status"] == "failed" and "damaged or password-protected" in bad_pdf["status_detail"]
    good = png_bytes(seed=909)
    bad_png = post("trunc.png", good[: len(good) // 3], "image/png").json()[0]["upload"]
    assert bad_png["status"] == "failed" and "couldn't open this image" in bad_png["status_detail"]
    assert admin_client.get("/health").status_code == 200                     # the app is still up
    assert admin_client.post(f"/clients/{cid}/uploads/{bad_pdf['id']}/retry").status_code == 200     # and failed files can be retried


def test_case_05_blurry_invoice_low_confidence_goes_to_review_not_guessed(admin_client, world, key):
    """REAL: heavy blur doesn't crash preprocessing. MECHANISM: when the model says it can't read a field (null / low
    confidence) the field is kept empty or sent to review, never filled in. Whether a real model behaves this way is untested."""
    entry = pick(key, "phone_photo")[0]
    img = Image.open(SYN / entry["file"]).convert("RGB").filter(ImageFilter.GaussianBlur(9))
    assert len(prepare_page(img)) > 1000
    blurred = io.BytesIO()
    img.save(blurred, "JPEG")
    low = json.loads(page_json(inv="BLUR-1", vin="1M8GDM9AXKP04278?", conf=0.95))
    low["header"]["odometer"] = {"value": None, "confidence": 0.0}               # model: "can't read this"
    low["header"]["vin"] = {"value": "1M8GDM9AXKP04278", "confidence": 0.35}     # model: unsure, 16 characters
    low["header"]["unit_number"] = {"value": "T-1?4", "confidence": 0.4}
    FakeProvider.reset()
    FakeProvider.scripted = [json.dumps(low)]
    up = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("blur.jpg", blurred.getvalue(), "image/jpeg"))]).json()[0]["upload"]
    assert up["status"] == "needs_review"
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "BLUR-1")
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["header"]["odometer"]["value"] is None                              # not guessed
    assert d["header"]["vin"]["needs_review"] and d["header"]["unit_number"]["needs_review"]
    assert "Check this" in d["header"]["vin"]["note"] and inv["fields_to_check"] >= 2


def test_case_08_too_little_data_skips_the_benchmark_check_with_a_note(admin_client, world):
    from datetime import date
    from decimal import Decimal as D

    from app.flags.engine import run_flag_engine

    from .test_flags_engine import add_invoice

    with client_session(world["a"]) as db:
        for i in range(3):   # only 3 samples; 5 are needed
            add_invoice(db, f"S{i}", date(2025, 1 + i, 5), unit=f"U{i}", lines=[("R&R water pump", "042-001-002", D("2.0"), D("100"), None, D("200"))], total=D("200"))
        add_invoice(db, "HUGE", date(2025, 9, 5), unit="U9", lines=[("R&R water pump", "042-001-002", D("9.0"), D("100"), None, D("900"))], total=D("900"))
        db.commit()
        FakeProvider.reset()
        s = run_flag_engine(db)
        db.commit()
    assert not [f for f in admin_client.get(f"/clients/{world['a']}/flags?type=labour_over_benchmark").json()["flags"]]
    assert any("not enough data" in n for n in s["notes"])


def test_truncated_images_are_rejected_even_after_the_report_module_is_loaded():
    from PIL import ImageFile

    import app.services.report_pdf  # noqa: F401  (imports WeasyPrint, which sets LOAD_TRUNCATED_IMAGES = True)
    from app.services.preprocess import UnreadableFile

    good = png_bytes(seed=5150)
    with pytest.raises(UnreadableFile, match="couldn't open this image"):
        render_pages(good[: len(good) // 3], "png")
