"""Database engine, session and per-client isolation.

Isolation model
---------------
Every client-owned model inherits ``ClientScoped``. A session is bound to one
client with ``bind_client(session, client_id)``. A ``do_orm_execute`` hook then
adds ``WHERE <table>.client_id = :client_id`` to every SELECT/UPDATE/DELETE that
touches a ClientScoped model, including relationship loads and joins.

If a query touches a ClientScoped model and the session has no client bound,
the hook raises ``UnscopedQueryError``. The only way past it is an explicit
``system_session()`` (used by background jobs that iterate clients and by
admin-only cross-client views), which is greppable and audited.

New rows: ``before_flush`` stamps ``client_id`` on new ClientScoped objects and
refuses objects whose ``client_id`` differs from the bound client.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import DateTime, ForeignKey, create_engine, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    declared_attr,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)

from .config import get_settings

CLIENT_KEY = "client_id"
SYSTEM_KEY = "system"


class UnscopedQueryError(RuntimeError):
    pass


class CrossClientWriteError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ClientScoped:
    """Mixin for every table that belongs to a single client."""

    @declared_attr
    def client_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False
        )


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def bind_client(session: Session, client_id: uuid.UUID) -> Session:
    session.info[CLIENT_KEY] = client_id
    return session


def _touches_scoped(state: ORMExecuteState) -> bool:
    for m in state.all_mappers:
        if issubclass(m.class_, ClientScoped):
            return True
    return False


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    session = state.session
    if session.info.get(SYSTEM_KEY):
        return
    client_id = session.info.get(CLIENT_KEY)
    if client_id is None:
        if _touches_scoped(state):
            raise UnscopedQueryError(
                "Query on client data without a bound client. Use bind_client() or system_session()."
            )
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            ClientScoped,
            lambda cls: cls.client_id == client_id,
            include_aliases=True,
            track_closure_variables=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_client(session: Session, flush_context, instances) -> None:  # noqa: ANN001
    if session.info.get(SYSTEM_KEY):
        return
    client_id = session.info.get(CLIENT_KEY)
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, ClientScoped):
            continue
        if client_id is None:
            raise UnscopedQueryError("Writing client data without a bound client.")
        if obj.client_id is None:
            obj.client_id = client_id
        elif obj.client_id != client_id:
            raise CrossClientWriteError("Object belongs to a different client than the session.")


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def system_session() -> Iterator[Session]:
    """Unscoped session for jobs and admin views. Use sparingly; every call site is reviewed."""
    db = SessionLocal()
    db.info[SYSTEM_KEY] = True
    try:
        yield db
    finally:
        db.close()


@contextmanager
def client_session(client_id: uuid.UUID) -> Iterator[Session]:
    db = SessionLocal()
    bind_client(db, client_id)
    try:
        yield db
    finally:
        db.close()
