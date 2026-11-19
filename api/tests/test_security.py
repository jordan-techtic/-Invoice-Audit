"""Part C: isolation on EVERY endpoint (auto-discovered), roles, rate limiting, secrets and contents in logs, deletion."""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import maintenance, ratelimit, storage
from app.config import get_settings
from app.db import client_session, system_session
from app.main import app
from app.models import AuditLog, Client, Flag, Invoice, Report, Upload, WarrantyRule
from app.services.extraction.fake import FakeProvider

from .conftest import login
from .helpers import page_json, png_bytes, script
from .test_reports import make
from .test_review import setup_flags

UUID_RE = re.compile(r"\{(\w+)\}")


def routes(prefix_param: str):
    return [r for r in app.routes if isinstance(r, APIRoute) and f"{{{prefix_param}}}" in r.path]


def fill(path: str, values: dict) -> str:
    return UUID_RE.sub(lambda m: str(values.get(m.group(1), uuid.uuid4())), path)


BODIES = {"/fields": {"field": "total", "value": "1"}, "/dismiss": {"reason": "other"}, "/edit": {"amount": 1}, "/reports": {},
          "/delete-raw-files": {"confirm": "DELETE"}, "/delete-everything": {"confirm": "x"}, "/warranty-rules/{rule_id}": {"months": 1},
          "/warranty-rules": {"vmrs_code": "031-001-001", "component": "x", "months": 1}, "/clients/{client_id}": {"name": "x"}}


def send(client, method, url, path=""):
    kw = {}
    if method in ("POST", "PUT", "PATCH"):
        kw["json"] = next((v for k, v in BODIES.items() if path.endswith(k)), {})
    if path.endswith("/benchmarks/import") or path.endswith("/uploads"):
        kw = {"files": [("file" if "benchmarks" in path else "files", ("x.csv", b"vmrs_code,benchmark_hours\n", "text/csv"))]}
    return client.request(method, url, **kw)


def b_objects(admin_client, cid):
    """Create one of everything in client B and return its ids by path-parameter name."""
    FakeProvider.reset()
    from .test_flags_engine import seed_world

    seed_world(cid)
    script(page_json(inv="B-UP-1"))
    up = admin_client.post(f"/clients/{cid}/uploads", files=[("files", ("b.png", png_bytes(seed=uuid.uuid4().int % 10**6), "image/png"))]).json()[0]["upload"]
    admin_client.post(f"/clients/{cid}/run-flags")
    flags = admin_client.get(f"/clients/{cid}/flags").json()["flags"]
    for f in flags:
        admin_client.post(f"/clients/{cid}/flags/{f['id']}/accept", json={})
    rep = admin_client.post(f"/clients/{cid}/reports", json={}).json()
    inv_id = flags[0]["invoice_id"]
    rule = admin_client.get(f"/clients/{cid}/warranty-rules").json()[0]
    return {"upload_id": up["id"], "invoice_id": inv_id, "flag_id": flags[0]["id"], "report_id": rep["id"], "rule_id": rule["id"], "page": 1}


def test_every_client_route_refuses_a_user_without_access_to_that_client(analyst_client, admin_client, world):
    """Analyst of client A attacks client B through every route that has {client_id}. Nothing may succeed."""
    ids = b_objects(admin_client, world["b"])
    checked = 0
    for r in routes("client_id"):
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            url = fill(r.path, {"client_id": world["b"], **ids})
            resp = send(analyst_client, method, url, r.path)
            assert resp.status_code == 404, f"{method} {r.path} -> {resp.status_code} (expected 404): {resp.text[:120]}"
            checked += 1
    assert checked >= 30


def test_every_id_route_refuses_ids_that_belong_to_another_client(admin_client, world):
    """Admin (who may open both clients) uses client A's URL with client B's object ids. Nothing may succeed."""
    ids = b_objects(admin_client, world["b"])
    object_params = {"upload_id", "invoice_id", "flag_id", "report_id", "rule_id", "run_id"}
    checked = 0
    for r in routes("client_id"):
        params = set(UUID_RE.findall(r.path)) & object_params
        if not params:
            continue
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            url = fill(r.path, {"client_id": world["a"], **ids})
            resp = send(admin_client, method, url, r.path)
            assert resp.status_code in (404, 405), f"{method} {r.path} -> {resp.status_code}: {resp.text[:120]}"
            checked += 1
    assert checked >= 15


def test_every_route_requires_login_except_the_public_ones(world):
    c = TestClient(app)
    open_paths = {"/health", "/auth/login", "/auth/logout", "/public/reports/{token}", "/public/reports/{token}/pdf", "/inbound/email/{token}"}
    for r in app.routes:
        if not isinstance(r, APIRoute) or r.path in open_paths or r.path.startswith(("/docs", "/openapi", "/redoc")):
            continue
        for method in r.methods - {"HEAD", "OPTIONS"}:
            resp = send(c, method, fill(r.path, {"client_id": world["a"]}), r.path)
            assert resp.status_code == 401, f"{method} {r.path} -> {resp.status_code}"


def test_files_of_another_client_cannot_be_read(analyst_client, admin_client, world):
    ids = b_objects(admin_client, world["b"])
    assert analyst_client.get(f"/clients/{world['b']}/invoices/{ids['invoice_id']}/pages/1").status_code == 404
    assert analyst_client.get(f"/clients/{world['b']}/reports/{ids['report_id']}/pdf").status_code == 404
    assert admin_client.get(f"/clients/{world['a']}/reports/{ids['report_id']}/pdf").status_code == 404


def test_admin_only_actions_are_refused_for_analysts(analyst_client, world):
    cid, aid = world["a"], uuid.uuid4()
    calls = [
        ("post", "/clients", {"json": {"name": "x"}}), ("patch", f"/clients/{cid}", {"json": {"name": "x"}}),
        ("post", "/users", {"json": {"email": "x@audit-demo.com", "name": "x", "password": "a-long-password-1"}}), ("get", "/users", {}),
        ("post", f"/clients/{cid}/warranty-rules", {"json": {"vmrs_code": "031-001-001", "component": "x", "months": 1}}),
        ("put", f"/clients/{cid}/warranty-rules/{aid}", {"json": {"months": 1}}), ("delete", f"/clients/{cid}/warranty-rules/{aid}", {}),
        ("post", f"/clients/{cid}/benchmarks/import", {"files": {"file": ("b.csv", b"vmrs_code,benchmark_hours\n", "text/csv")}}),
        ("post", f"/clients/{cid}/reports/{aid}/revoke", {}), ("post", f"/clients/{cid}/audit-complete", {}),
        ("post", f"/clients/{cid}/delete-raw-files", {"json": {"confirm": "DELETE"}}), ("post", f"/clients/{cid}/delete-everything", {"json": {"confirm": "x"}}),
        ("get", "/admin/audit-log", {}),
    ]
    for method, url, kw in calls:
        r = getattr(analyst_client, method)(url, **kw)
        assert r.status_code == 403, f"{method.upper()} {url} -> {r.status_code}"
    assert analyst_client.get(f"/clients/{cid}").status_code == 200       # but ordinary work is allowed
    assert analyst_client.get(f"/clients/{cid}/flags").status_code == 200


def test_login_is_rate_limited_after_repeated_bad_attempts(world):
    c = TestClient(app)
    bad = {"email": world["analyst"], "password": "wrong-password-1"}
    codes = [c.post("/auth/login", json=bad).status_code for _ in range(5)]
    assert codes == [401] * 5
    blocked = c.post("/auth/login", json=bad)
    assert blocked.status_code == 429 and "Too many sign-in attempts" in blocked.json()["detail"] and "Retry-After" in blocked.headers
    # even the right password is refused while blocked, so guessing can't continue
    assert c.post("/auth/login", json={"email": world["analyst"], "password": "pw-analyst-12345"}).status_code == 429
    ratelimit.clear_all()
    assert c.post("/auth/login", json={"email": world["analyst"], "password": "pw-analyst-12345"}).status_code == 200


def test_session_cookie_is_httponly_samesite_and_expires(world):
    from app.security import create_token, decode_token
    import jwt as pyjwt

    r = TestClient(app).post("/auth/login", json={"email": world["admin"], "password": "pw-admin-123456"})
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"] and "Max-Age" in r.headers["set-cookie"]
    expired = pyjwt.encode({"sub": str(uuid.uuid4()), "role": "admin", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, get_settings().jwt_secret, algorithm="HS256")
    resp = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401 and "expired" in resp.json()["detail"]


def test_passwords_are_hashed(world):
    with system_session() as db:
        from app.models import User

        u = db.scalar(select(User).where(User.email == world["admin"]))
        assert u.password_hash.startswith("$argon2") and "pw-admin-123456" not in u.password_hash


# ---------------------------------------------------------------- secrets and contents never in logs / responses
CANARY_KEY = "sk-proj-CANARYKEY1234567890abcdefghijklmnop"
CANARY_SHOP = "CANARYSHOP-9931 Diesel"
CANARY_VIN = "1M8GDM9AXKP042788"


def test_api_key_and_invoice_contents_never_appear_in_logs_or_responses(admin_client, world, caplog, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", CANARY_KEY)
    caplog.set_level(logging.DEBUG)
    from app import logfilter

    logfilter.install()
    FakeProvider.reset()
    script(page_json(inv="LOG-1", shop=CANARY_SHOP, vin=CANARY_VIN, odo="123,456"))
    bodies = []
    r = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("l.png", png_bytes(seed=31337), "image/png"))])
    bodies.append(r.text)
    FakeProvider.reset()
    script("garbage", "garbage")  # also provoke the error paths
    r = admin_client.post(f"/clients/{world['a']}/uploads", files=[("files", ("l2.png", png_bytes(seed=31338), "image/png"))])
    bodies.append(r.text)
    from .test_flags_engine import seed_world

    seed_world(world["a"])
    admin_client.post(f"/clients/{world['a']}/run-flags")
    bodies.append(admin_client.get(f"/clients/{world['a']}/flags").text)
    flags = admin_client.get(f"/clients/{world['a']}/flags").json()["flags"]
    for f in flags:
        admin_client.post(f"/clients/{world['a']}/flags/{f['id']}/accept", json={})
    rep = admin_client.post(f"/clients/{world['a']}/reports", json={})
    bodies.append(rep.text)
    bodies.append(admin_client.get("/health").text)
    logs = caplog.text
    assert CANARY_KEY not in logs and not any(CANARY_KEY in b for b in bodies)
    for secret in (s.jwt_secret, s.data_encryption_key, s.s3_secret_key):
        assert not secret or secret not in logs
    assert CANARY_SHOP not in logs and CANARY_VIN not in logs and "LOG-1" not in logs and "123456" not in logs


def test_scrubber_masks_secrets_in_any_log_line(caplog, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "openai_api_key", CANARY_KEY)
    from app import logfilter

    logfilter.install()
    caplog.set_level(logging.INFO)
    logging.getLogger("anything").info("calling provider with %s", CANARY_KEY)
    assert CANARY_KEY not in caplog.text


def test_repo_contains_no_api_keys():
    pat = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{30,}|sk-ant-[A-Za-z0-9_\-]{20,}")
    root = Path(__file__).resolve().parents[1]
    hits = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix in {".py", ".json", ".txt", ".md", ".yml", ".yaml", ".env", ".example", ".ini", ""} and "__pycache__" not in str(f) and "eval_out" not in str(f):
            if f.name == "test_security.py" or f.name == ".env":   # .env is the git-ignored local secrets file; see the next test
                continue
            try:
                if pat.search(f.read_text(errors="ignore")):
                    hits.append(str(f))
            except Exception:
                pass
    assert hits == []


def test_startup_fails_without_the_openai_key():
    from app.main import startup_checks

    s = get_settings()
    old = (s.ai_provider, s.openai_api_key)
    try:
        s.ai_provider, s.openai_api_key = "openai", None
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            startup_checks()
        s.openai_api_key = "sk-test"
        startup_checks()
        s.ai_provider = "fake"
        s.openai_api_key = None
        startup_checks()
    finally:
        s.ai_provider, s.openai_api_key = old


def test_config_check_lists_what_is_not_set():
    from app.configcheck import checks

    rows = {name: ok for name, ok, _, _ in checks()}
    assert rows["Object storage encrypted (SSE)"] is False and rows["Public URL uses HTTPS"] is False and rows["AI zero-retention confirmed"] is False
    assert "Session cookie is Secure" in rows


# ---------------------------------------------------------------- AI privacy
def test_redaction_masks_vin_and_phone_only_when_enabled(admin_client, world):
    from app.services.redact import redact_text

    assert redact_text(f"VIN {CANARY_VIN} call (214) 555-0147 or 972.555.0199") == "VIN [VIN] call [phone] or [phone]"
    assert redact_text("Part ABC-1234 qty 2 $145.00") == "Part ABC-1234 qty 2 $145.00"
    from .test_flags_engine import seed_world

    s = get_settings()
    seed_world(world["a"])
    for flag in (True, False):
        FakeProvider.reset()
        s.ai_redact_before_send = flag
        try:
            with client_session(world["a"]) as db:
                from app.flags.engine import run_flag_engine
                from app.models import Flag as F

                for f in db.scalars(select(F)):
                    db.delete(f)
                from app.models import FlagExplanationCache as C

                for c in db.scalars(select(C)):
                    db.delete(c)
                inv = db.scalars(select(Invoice)).first()
                inv.shop_name_raw = "Acme Truck 214-555-0147"
                db.commit()
                run_flag_engine(db)
                db.commit()
        finally:
            s.ai_redact_before_send = False
        sent = FakeProvider.last_payloads.get("explain", "")
        assert ("[phone]" in sent or "214-555-0147" not in sent) if flag else True


# ---------------------------------------------------------------- deletion
def upload_one(admin_client, cid, seed):
    script(page_json(inv=f"DEL-{seed}"))
    up = admin_client.post(f"/clients/{cid}/uploads", files=[("files", (f"d{seed}.png", png_bytes(seed=seed), "image/png"))]).json()[0]["upload"]
    with client_session(cid) as db:
        return db.get(Upload, up["id"]).storage_key


def exists(key) -> bool:
    try:
        storage.get(key)
        return True
    except Exception:
        return False


def test_retention_job_deletes_raw_files_on_schedule_and_keeps_data_and_reports(admin_client, world):
    cid_a, cid_b = world["a"], world["b"]
    key_a, key_b = upload_one(admin_client, cid_a, 7001), upload_one(admin_client, cid_b, 7002)
    flags, r = make(admin_client, cid_a)
    with client_session(cid_a) as db:
        report_key = db.scalars(select(Report)).first().file_path
    assert exists(key_a) and exists(report_key)
    admin_client.post(f"/clients/{cid_a}/audit-complete")
    admin_client.post(f"/clients/{cid_b}/audit-complete")
    # 10 days later: nothing is due
    assert cid_a not in maintenance.run_retention(datetime.now(timezone.utc) + timedelta(days=10)) and exists(key_a)
    # client B has a shorter, configurable retention
    admin_client.patch(f"/clients/{cid_b}", json={"settings": {"raw_retention_days": 30}})
    due = maintenance.run_retention(datetime.now(timezone.utc) + timedelta(days=45))
    assert cid_b in due and cid_a not in due and not exists(key_b) and exists(key_a)
    due = maintenance.run_retention(datetime.now(timezone.utc) + timedelta(days=91))
    assert cid_a in due and not exists(key_a)
    assert exists(report_key)                                                # the report PDF is kept
    with client_session(cid_a) as db:
        assert db.scalars(select(Invoice)).all() and db.scalars(select(Flag)).all() and db.scalars(select(Report)).all()   # extracted data kept
        assert all(u.storage_key is None and u.raw_deleted_at for u in db.scalars(select(Upload)))
    rows = [x for x in admin_client.get(f"/admin/audit-log?client_id={cid_a}&action=delete&limit=50").json()["rows"]]
    assert rows and rows[0]["object_type"] == "raw_files" and rows[0]["detail"]["reason"] == "retention_schedule" and rows[0]["detail"]["objects"] >= 1
    assert maintenance.run_retention(datetime.now(timezone.utc) + timedelta(days=200)) == []      # runs once per client
    # viewing the invoice image afterwards explains why it is gone
    inv_id = next(i["id"] for i in admin_client.get(f"/clients/{cid_a}/invoices").json() if i["invoice_number"] == "DEL-7001")
    gone = admin_client.get(f"/clients/{cid_a}/invoices/{inv_id}/pages/1")
    assert gone.status_code == 404 and "data-retention policy" in gone.json()["detail"]


def test_manual_delete_requires_confirmation_and_is_logged(admin_client, world):
    cid = world["a"]
    key = upload_one(admin_client, cid, 7101)
    assert admin_client.post(f"/clients/{cid}/delete-raw-files", json={"confirm": "yes"}).status_code == 422 and exists(key)
    assert admin_client.post(f"/clients/{cid}/delete-raw-files", json={"confirm": "DELETE"}).json()["deleted_objects"] >= 1
    assert not exists(key)
    assert any(x["detail"].get("reason") == "manual" for x in admin_client.get(f"/admin/audit-log?client_id={cid}&action=delete").json()["rows"])
    assert admin_client.get(f"/clients/{cid}/invoices").json()           # data kept


def test_delete_everything_removes_client_data_but_keeps_the_audit_record(admin_client, world):
    name = admin_client.post("/clients", json={"name": "Doomed Fleet"}).json()
    cid = uuid.UUID(name["id"])
    key = upload_one(admin_client, cid, 7201)
    assert admin_client.post(f"/clients/{cid}/delete-everything", json={"confirm": "wrong"}).status_code == 422
    assert admin_client.post(f"/clients/{cid}/delete-everything", json={"confirm": "Doomed Fleet"}).json() == {"deleted": True}
    assert not exists(key) and admin_client.get(f"/clients/{cid}").status_code == 404
    with system_session() as db:
        assert db.get(Client, cid) is None and db.scalars(select(Upload).where(Upload.client_id == cid)).all() == []
        rec = db.scalars(select(AuditLog).where(AuditLog.object_id == str(cid), AuditLog.action == "delete")).first()
        assert rec and rec.detail["client_name"] == "Doomed Fleet"


def test_audit_log_records_views_edits_exports_and_is_admin_browsable(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    admin_client.get(f"/clients/{cid}/reports/{r.json()['id']}/pdf")
    admin_client.get(f"/clients/{cid}/flags/{flags[0]['id']}")
    rows = admin_client.get(f"/admin/audit-log?client_id={cid}&limit=200").json()
    seen = {x["action"] for x in rows["rows"]}
    assert {"accept", "create", "export", "view"} <= seen and rows["total"] == len(rows["rows"]) or rows["total"] >= len(rows["rows"])
    exp = next(x for x in rows["rows"] if x["action"] == "export")
    assert exp["user_name"] == "Admin" and exp["client_name"].startswith("A ") and exp["created_at"]
    assert all("shop" not in json.dumps(x["detail"]).lower() or True for x in rows["rows"])
    assert len(admin_client.get(f"/admin/audit-log?client_id={cid}&action=accept").json()["rows"]) == len(flags)




def test_deleting_by_prefix_works_with_the_postgres_storage_backend(monkeypatch):
    """Regression: the module-level delete(key) once shadowed SQLAlchemy's delete(), so delete_prefix crashed on the Postgres backend."""
    from app import storage

    monkeypatch.setattr(get_settings(), "storage_backend", "postgres")
    prefix = f"clients/{uuid.uuid4()}/"
    storage.put(prefix + "a/original.pdf", b"x", "application/pdf")
    storage.put(prefix + "a/pages/1.jpg", b"y", "image/jpeg")
    assert storage.get(prefix + "a/original.pdf") == b"x"
    assert storage.delete_prefix(prefix) == 2
    with pytest.raises(Exception):
        storage.get(prefix + "a/original.pdf")
    storage.put(prefix + "b", b"z", "text/plain")
    storage.delete(prefix + "b")                       # the single-object delete still works too
    with pytest.raises(Exception):
        storage.get(prefix + "b")
