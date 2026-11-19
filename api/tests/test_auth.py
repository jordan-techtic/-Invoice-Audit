from fastapi.testclient import TestClient

from app.main import app


def test_health():
    assert TestClient(app).get("/health").json() == {"ok": True}


def test_login_wrong_password_is_rejected(world):
    r = TestClient(app).post("/auth/login", json={"email": world["admin"], "password": "nope-nope-nope"})
    assert r.status_code == 401
    assert "don't match" in r.json()["detail"]


def test_me_requires_login():
    assert TestClient(app).get("/auth/me").status_code == 401


def test_login_sets_httponly_cookie(world):
    r = TestClient(app).post("/auth/login", json={"email": world["admin"], "password": "pw-admin-123456"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_me(admin_client):
    assert admin_client.get("/auth/me").json()["role"] == "admin"


def test_analyst_cannot_create_clients_or_users(analyst_client):
    assert analyst_client.post("/clients", json={"name": "X"}).status_code == 403
    assert analyst_client.get("/users").status_code == 403


def test_admin_creates_client_with_default_warranty_rules(admin_client):
    r = admin_client.post("/clients", json={"name": "New Fleet Co"})
    assert r.status_code == 201
    body = r.json()
    assert body["settings"]["labour_over_benchmark_pct"] == 20
    assert body["inbound_email_token"]


def test_unknown_setting_rejected(admin_client, world):
    r = admin_client.patch(f"/clients/{world['a']}", json={"settings": {"bogus": 1}})
    assert r.status_code == 422
