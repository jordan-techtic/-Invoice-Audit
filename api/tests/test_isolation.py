"""Proves one client can't read or write another client's data."""

import pytest
from sqlalchemy import select

from app.db import CrossClientWriteError, SessionLocal, UnscopedQueryError, client_session
from app.models import WarrantyRule


def test_scoped_session_only_sees_own_rows(world):
    with client_session(world["a"]) as db:
        rules = db.scalars(select(WarrantyRule)).all()
    assert rules and all(r.client_id == world["a"] for r in rules)
    assert all(r.component != "Alternator B" for r in rules)


def test_get_by_primary_key_of_other_client_returns_nothing(world):
    with client_session(world["b"]) as db:
        b_rule = db.scalars(select(WarrantyRule)).first()
        b_id = b_rule.id
    with client_session(world["a"]) as db:
        # Even a direct id lookup is filtered.
        assert db.scalars(select(WarrantyRule).where(WarrantyRule.id == b_id)).first() is None


def test_unbound_session_refuses_client_queries(world):
    db = SessionLocal()
    try:
        with pytest.raises(UnscopedQueryError):
            db.scalars(select(WarrantyRule)).all()
    finally:
        db.close()


def test_cannot_write_into_other_client(world):
    with client_session(world["a"]) as db:
        db.add(WarrantyRule(client_id=world["b"], vmrs_code="032-001-001", component="x", months=1))
        with pytest.raises(CrossClientWriteError):
            db.flush()


def test_new_rows_are_stamped_with_bound_client(world):
    with client_session(world["a"]) as db:
        r = WarrantyRule(vmrs_code="042-001-002", component="Water pump", months=12)
        db.add(r)
        db.flush()
        assert r.client_id == world["a"]
        db.rollback()


def test_bulk_update_is_scoped(world):
    from sqlalchemy import update

    with client_session(world["a"]) as db:
        db.execute(update(WarrantyRule).values(months=99))
        db.commit()
    with client_session(world["b"]) as db:
        assert all(r.months != 99 for r in db.scalars(select(WarrantyRule)).all())


def test_analyst_api_cannot_open_unassigned_client(analyst_client, world):
    assert analyst_client.get(f"/clients/{world['a']}").status_code == 200
    # 404 (not 403) so the existence of other clients isn't revealed
    assert analyst_client.get(f"/clients/{world['b']}").status_code == 404
    ids = {c["id"] for c in analyst_client.get("/clients").json()}
    assert str(world["a"]) in ids and str(world["b"]) not in ids
