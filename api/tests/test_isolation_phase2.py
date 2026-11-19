"""Every Phase 2 endpoint refuses access across clients."""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.security import hash_password

from .conftest import login
from .helpers import page_json, png_bytes, script


def _seed_invoice(admin_client, cid):
    script(page_json(inv=f"ISO-{uuid.uuid4().hex[:5]}"))
    up = admin_client.post(f"/clients/{cid}/uploads", files=[("files", ("i.png", png_bytes(seed=int(uuid.uuid4().int % 10**6)), "image/png"))]).json()[0]["upload"]
    inv = admin_client.get(f"/clients/{cid}/invoices").json()[0]
    return up, inv


def test_analyst_of_client_a_cannot_touch_client_b_on_any_endpoint(admin_client, analyst_client, world):
    b = world["b"]
    up, inv = _seed_invoice(admin_client, b)
    base = f"/clients/{b}"
    calls = [
        ("get", f"{base}/uploads", None), ("post", f"{base}/uploads", "files"),
        ("post", f"{base}/uploads/{up['id']}/retry", None),
        ("get", f"{base}/invoices", None), ("get", f"{base}/invoices/{inv['id']}", None),
        ("get", f"{base}/invoices/{inv['id']}/pages/1", None),
        ("patch", f"{base}/invoices/{inv['id']}/fields", {"json": {"field": "total", "value": "1.00"}}),
        ("post", f"{base}/invoices/{inv['id']}/mark-checked", None),
    ]
    for method, url, extra in calls:
        kw = {}
        if extra == "files":
            kw["files"] = [("files", ("x.png", png_bytes(seed=999), "image/png"))]
        elif extra:
            kw = extra
        r = getattr(analyst_client, method)(url, **kw)
        assert r.status_code == 404, f"{method.upper()} {url} -> {r.status_code}"


def test_invoice_id_from_other_client_is_not_found_under_own_client(admin_client, world):
    _, inv_b = _seed_invoice(admin_client, world["b"])
    base = f"/clients/{world['a']}/invoices/{inv_b['id']}"
    assert admin_client.get(base).status_code == 404
    assert admin_client.get(f"{base}/pages/1").status_code == 404
    assert admin_client.patch(f"{base}/fields", json={"field": "total", "value": "1"}).status_code == 404
    assert admin_client.post(f"{base}/mark-checked").status_code == 404
    ids_a = {i["id"] for i in admin_client.get(f"/clients/{world['a']}/invoices").json()}
    assert inv_b["id"] not in ids_a


def test_upload_id_from_other_client_cannot_be_retried(admin_client, world):
    script("bad", "bad")
    up = admin_client.post(f"/clients/{world['b']}/uploads", files=[("files", ("f.png", png_bytes(seed=555), "image/png"))]).json()[0]["upload"]
    assert up["status"] == "failed"
    assert admin_client.post(f"/clients/{world['a']}/uploads/{up['id']}/retry").status_code == 404


def test_endpoints_require_login():
    c = TestClient(app)
    cid = uuid.uuid4()
    for method, url in [("get", f"/clients/{cid}/uploads"), ("get", f"/clients/{cid}/invoices"), ("post", f"/clients/{cid}/uploads")]:
        assert getattr(c, method)(url).status_code == 401


def test_storage_keys_are_prefixed_with_client_id(admin_client, world):
    from sqlalchemy import select

    from app.db import client_session
    from app.models import Upload

    script(page_json(inv="KEY-1"))
    up = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("k.png", png_bytes(seed=777), "image/png"))]).json()[0]["upload"]
    with client_session(world["a"]) as db:
        key = db.scalars(select(Upload).where(Upload.id == up["id"])).one().storage_key
    assert key.startswith(f"clients/{world['a']}/{up['id']}/")
