import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://audit:audit@db:5432/audit_test")
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/audit_test"
os.environ["AI_PROVIDER"] = "fake"
os.environ["QUEUE_INLINE"] = "true"
os.environ.setdefault("STORAGE_BACKEND", "postgres")
# Keep password/session auth on for security tests (app defaults to auth off).
os.environ["AUTH_DISABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, system_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Client, Role, User, UserClient, WarrantyRule  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.seed import seed_vmrs  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with system_session() as db:
        seed_vmrs(db)
        db.commit()
    from app import storage

    storage.ensure_bucket()
    yield


@pytest.fixture()
def world():
    """Two clients, one admin, one analyst assigned only to client A."""
    tag = uuid.uuid4().hex[:6]
    with system_session() as db:
        a = Client(name=f"A {tag}", slug=f"a-{tag}", inbound_email_token=f"a{tag}", settings={})
        b = Client(name=f"B {tag}", slug=f"b-{tag}", inbound_email_token=f"b{tag}", settings={})
        admin = User(email=f"admin-{tag}@audit-demo.com", name="Admin", role=Role.admin, password_hash=hash_password("pw-admin-123456"))
        analyst = User(email=f"an-{tag}@audit-demo.com", name="Analyst", role=Role.analyst, password_hash=hash_password("pw-analyst-12345"))
        db.add_all([a, b, admin, analyst])
        db.flush()
        db.add(UserClient(user_id=analyst.id, client_id=a.id))
        db.add(WarrantyRule(client_id=a.id, vmrs_code="031-001-001", component="Alternator A", months=12, miles=100000))
        db.add(WarrantyRule(client_id=b.id, vmrs_code="031-001-001", component="Alternator B", months=6, miles=50000))
        db.commit()
        return {"a": a.id, "b": b.id, "admin": admin.email, "analyst": analyst.email}


def login(email: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def admin_client(world):
    return login(world["admin"], "pw-admin-123456")


@pytest.fixture()
def analyst_client(world):
    return login(world["analyst"], "pw-analyst-12345")


@pytest.fixture(autouse=True)
def _fresh_limits():
    from app import ratelimit

    ratelimit.clear_all()
    yield
    ratelimit.clear_all()
