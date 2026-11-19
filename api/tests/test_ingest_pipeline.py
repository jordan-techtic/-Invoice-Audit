import json

from sqlalchemy import select

from app.db import client_session
from app.models import ExtractionRun, FieldConfidence, Invoice, Upload
from app.security import decrypt_bytes
from app.services.extraction.fake import FakeProvider

from .helpers import page_json, pdf_bytes, png_bytes, script


def post(c, cid, *files):
    return c.post(f"/clients/{cid}/uploads", files=[("files", f) for f in files])


def test_rejects_wrong_type_and_empty_and_oversize(admin_client, world):
    r = post(admin_client, world["a"], ("notes.txt", b"hello", "text/plain"), ("e.png", b"", "image/png"))
    res = r.json()
    assert [x["ok"] for x in res] == [False, False]
    assert "isn't a PDF, JPG, PNG or HEIC" in res[0]["error"] and "empty" in res[1]["error"]
    from app.config import get_settings

    big = b"%PDF-" + b"0" * (get_settings().max_upload_mb * 1024 * 1024)
    assert "larger than 25 MB" in post(admin_client, world["a"], ("big.pdf", big, "application/pdf")).json()[0]["error"]


def test_type_is_detected_by_content_not_name(admin_client, world):
    r = post(admin_client, world["a"], ("fake.pdf", b"not really a pdf at all", "application/pdf"))
    assert r.json()[0]["ok"] is False


def test_exact_duplicate_is_skipped_with_reason(admin_client, world):
    script(page_json(inv="D1"))
    data = png_bytes(seed=101)
    first = post(admin_client, world["a"], ("one.png", data, "image/png")).json()[0]["upload"]
    second = post(admin_client, world["a"], ("copy-of-one.png", data, "image/png")).json()[0]["upload"]
    assert first["status"] in ("done", "needs_review") and second["status"] == "duplicate"
    assert second["duplicate_of"] == first["id"]
    assert "identical to one.png" in second["status_detail"]
    assert FakeProvider.extract_calls == 1  # the copy was never sent to the AI


def test_same_file_in_other_client_is_not_a_duplicate(admin_client, world):
    data = png_bytes(seed=102)
    script(page_json(inv="X1"), page_json(inv="X1"))
    a = post(admin_client, world["a"], ("f.png", data, "image/png")).json()[0]["upload"]
    b = post(admin_client, world["b"], ("f.png", data, "image/png")).json()[0]["upload"]
    assert a["status"] != "duplicate" and b["status"] != "duplicate"


def test_single_invoice_end_to_end_clean(admin_client, world):
    script(page_json(inv="E2E-1"))
    up = post(admin_client, world["a"], ("inv.png", png_bytes(seed=103), "image/png")).json()[0]["upload"]
    assert up["status"] == "done" and up["invoice_count"] == 1
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "E2E-1")
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["header"]["invoice_date"]["value"] == "2026-03-14"      # normalised to ISO
    assert d["header"]["odometer"]["value"] == 412880
    assert d["header"]["vin"]["value"] == "1M8GDM9AXKP042788".upper()
    assert d["lines"][0]["vmrs_code"]["value"] == "031-001-001"      # "R&R alternator" via lookup, no AI call
    assert FakeProvider.classify_calls == 0
    assert inv["review_status"] == "ready" and inv["fields_to_check"] == 0
    img = admin_client.get(f"/clients/{world['a']}{d['pages'][0]['url'].removeprefix('/clients/' + str(world['a']))}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_low_confidence_field_goes_to_review_with_plain_note(admin_client, world):
    script(page_json(inv="LOW-1", odo="41?,880", conf=0.95).replace('"odometer": {"value": "41?,880", "confidence": 0.95}', '"odometer": {"value": "412880", "confidence": 0.55}'))
    up = post(admin_client, world["a"], ("low.png", png_bytes(seed=104), "image/png")).json()[0]["upload"]
    assert up["status"] == "needs_review"
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "LOW-1")
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["header"]["odometer"]["needs_review"] and d["header"]["odometer"]["note"] == "Check this: hard to read on the invoice."
    assert inv["fields_to_check"] == 1


def test_inline_edit_and_mark_as_checked(admin_client, world):
    script(page_json(inv="FIX-1").replace('"confidence": 0.95', '"confidence": 0.95', 1).replace(
        '"odometer": {"value": "412,880", "confidence": 0.95}', '"odometer": {"value": "412,880", "confidence": 0.5}'))
    up = post(admin_client, world["a"], ("fix.png", png_bytes(seed=105), "image/png")).json()[0]["upload"]
    inv_id = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "FIX-1")["id"]
    base = f"/clients/{world['a']}/invoices/{inv_id}"
    bad = admin_client.patch(f"{base}/fields", json={"field": "odometer", "value": "abc"})
    assert bad.status_code == 422 and "isn't a valid value" in bad.json()["detail"]
    ok = admin_client.patch(f"{base}/fields", json={"field": "odometer", "value": "412,885"})
    assert ok.status_code == 200
    d = admin_client.get(base).json()
    assert d["header"]["odometer"]["value"] == 412885 and not d["header"]["odometer"]["needs_review"] and d["header"]["odometer"]["corrected"]
    r = admin_client.post(f"{base}/mark-checked").json()
    assert r["review_status"] == "reviewed"
    uploads = {u["id"]: u for u in admin_client.get(f"/clients/{world['a']}/uploads").json()}
    assert uploads[up["id"]]["status"] == "done"


def test_multi_invoice_pdf_is_split_with_page_ranges(admin_client, world):
    script(
        page_json(inv="M-1", page=(1, 1)),
        page_json(inv="M-2", page=(1, 2), subtotal="100.00", total="100.00"),
        page_json(inv="M-2", page=(2, 2), subtotal="580.00", total="580.00"),
        page_json(inv="M-3", page=(1, 1)),
    )
    up = post(admin_client, world["a"], ("batch.pdf", pdf_bytes(4, seed=7), "application/pdf")).json()[0]["upload"]
    assert up["page_count"] == 4 and up["invoice_count"] == 3
    with client_session(world["a"]) as db:
        rows = db.scalars(select(Invoice).where(Invoice.invoice_number.in_(["M-1", "M-2", "M-3"])).order_by(Invoice.invoice_number)).all()
        assert [(r.invoice_number, r.page_start, r.page_end) for r in rows] == [("M-1", 1, 1), ("M-2", 2, 3), ("M-3", 4, 4)]


def test_sideways_page_is_rotated_and_reread(admin_client, world):
    script(page_json(inv="ROT-1", rotation=90, conf=0.2), page_json(inv="ROT-1"))
    up = post(admin_client, world["a"], ("side.png", png_bytes(seed=106), "image/png")).json()[0]["upload"]
    assert FakeProvider.extract_calls == 2 and up["status"] == "done"


def test_malformed_twice_marks_failed_then_retry_succeeds(admin_client, world):
    script("garbage", "garbage")
    up = post(admin_client, world["a"], ("bad.png", png_bytes(seed=107), "image/png")).json()[0]["upload"]
    assert up["status"] == "failed" and "Retry the file" in up["status_detail"]
    script(page_json(inv="RETRY-1"))
    r = admin_client.post(f"/clients/{world['a']}/uploads/{up['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert admin_client.post(f"/clients/{world['a']}/uploads/{up['id']}/retry").status_code == 409  # only failed files


def test_not_an_invoice_fails_with_next_step(admin_client, world):
    FakeProvider.reset()  # default: model says is_invoice=false
    up = post(admin_client, world["a"], ("blank.png", png_bytes(seed=108), "image/png")).json()[0]["upload"]
    assert up["status"] == "failed" and "couldn't find an invoice" in up["status_detail"]


def test_raw_model_response_is_stored_encrypted(admin_client, world):
    script(page_json(inv="ENC-1"))
    up = post(admin_client, world["a"], ("enc.png", png_bytes(seed=109), "image/png")).json()[0]["upload"]
    with client_session(world["a"]) as db:
        run = db.scalars(select(ExtractionRun).where(ExtractionRun.upload_id == up["id"])).first()
        assert b"ENC-1" not in run.raw_response_encrypted
        assert "ENC-1" in decrypt_bytes(run.raw_response_encrypted).decode()
        assert run.cost_usd > 0 and run.input_tokens > 0


def test_vmrs_ai_result_is_cached_by_description(admin_client, world):
    line = lambda d: [{"description": {"value": d, "confidence": 0.95}, "part_number": {"value": None, "confidence": 0}, "qty": {"value": 1, "confidence": .9},
                       "parts_price": {"value": "10.00", "confidence": .9}, "labour_hours": {"value": None, "confidence": 0}, "labour_rate": {"value": None, "confidence": 0},
                       "line_total": {"value": "10.00", "confidence": .9}}]
    FakeProvider.reset()
    FakeProvider.scripted = [page_json(inv="C-1", lines=line("misc hardware whatsit"), subtotal="10.00", total="10.00"),
                             page_json(inv="C-2", lines=line("Misc  Hardware, whatsit"), subtotal="10.00", total="10.00")]
    FakeProvider.classify_scripted = [json.dumps({"items": [{"index": 0, "vmrs_code": "014-001-003", "confidence": 0.65}]})]
    post(admin_client, world["a"], ("c1.png", png_bytes(seed=110), "image/png"))
    post(admin_client, world["a"], ("c2.png", png_bytes(seed=111), "image/png"))
    assert FakeProvider.classify_calls == 1  # second upload hit the cache (case/punctuation-insensitive)
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "C-1")
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["lines"][0]["vmrs_code"]["needs_review"]  # 0.65 < 0.80 -> review queue


def test_email_inbound_uses_same_pipeline(world):
    import base64

    from fastapi.testclient import TestClient

    from app.main import app

    script(page_json(inv="MAIL-1"))
    c = TestClient(app)
    token = "a" + world["a"].hex[:0]  # placeholder, real token fetched below
    from app.db import system_session
    from app.models import Client

    with system_session() as db:
        token = db.get(Client, world["a"]).inbound_email_token
    body = {"From": "shop@example.com", "Subject": "Invoice", "Attachments": [
        {"Name": "i.png", "ContentType": "image/png", "Content": base64.b64encode(png_bytes(seed=112)).decode()}]}
    assert c.post(f"/inbound/email/{token}", json=body).status_code == 401  # secret required
    r = c.post(f"/inbound/email/{token}", json=body, headers={"X-Inbound-Secret": "local-inbound-secret"})
    assert r.status_code == 200 and r.json()["results"][0]["upload"]["source"] == "email"
    assert c.post("/inbound/email/nope", json=body, headers={"X-Inbound-Secret": "local-inbound-secret"}).status_code == 404


def test_a_wild_vin_from_the_model_never_fails_the_whole_upload(admin_client, world):
    script(page_json(inv="WILD-1", vin="V" * 30, odo="412,880"))
    up = post(admin_client, world["a"], ("wild.png", png_bytes(seed=8801), "image/png")).json()[0]["upload"]
    assert up["status"] == "needs_review" and up["invoice_count"] == 1          # not 'failed'
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "WILD-1")
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["header"]["vin"]["value"] is None and d["header"]["vin"]["needs_review"] and "read as 30" in d["header"]["vin"]["note"]


def test_fee_lines_do_not_send_an_invoice_to_review_or_to_the_ai(admin_client, world):
    """Regression (found on the real-model run): 28% of lines are fees with no job code; they put ~half of all invoices into review."""
    fee = lambda d, p: {"description": {"value": d, "confidence": .95}, "part_number": {"value": None, "confidence": 1}, "qty": {"value": None, "confidence": 1},
                        "parts_price": {"value": None, "confidence": 1}, "labour_hours": {"value": None, "confidence": 1}, "labour_rate": {"value": None, "confidence": 1},
                        "line_total": {"value": p, "confidence": .95}}
    lines = [fee("Shop supplies", "12.00"), fee("Environmental fee", "8.50"),
             {**fee("R&R alternator", "580.00"), "qty": {"value": 1, "confidence": .95}, "parts_price": {"value": "350.00", "confidence": .95},
              "labour_hours": {"value": 2.0, "confidence": .95}, "labour_rate": {"value": "115.00", "confidence": .95}}]
    script(page_json(inv="FEE-1", lines=lines, subtotal="600.50", total="600.50"))
    up = post(admin_client, world["a"], ("fee.png", png_bytes(seed=8802), "image/png")).json()[0]["upload"]
    assert up["status"] == "done" and FakeProvider.classify_calls == 0          # fee lines were never sent to the classifier
    inv = next(i for i in admin_client.get(f"/clients/{world['a']}/invoices").json() if i["invoice_number"] == "FEE-1")
    assert inv["review_status"] == "ready" and inv["fields_to_check"] == 0
    d = admin_client.get(f"/clients/{world['a']}/invoices/{inv['id']}").json()
    assert d["lines"][0]["vmrs_code"]["value"] is None and not d["lines"][0]["vmrs_code"]["needs_review"]
    assert d["lines"][2]["vmrs_code"]["value"] == "031-001-001"
