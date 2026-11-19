"""Request dependencies: current user, role checks, and the client-bound session."""

from __future__ import annotations

import uuid
from typing import Iterator

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, bind_client
from .models import Client, Role, User, UserClient
from .security import decode_token

COOKIE_NAME = "audit_session"


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _bypass_user(db: Session) -> User:
    user = db.scalars(
        select(User).where(User.role == Role.admin, User.is_active.is_(True)).order_by(User.created_at).limit(1)
    ).first()
    if user is None:
        user = db.scalars(select(User).where(User.is_active.is_(True)).limit(1)).first()
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No users in database. Run: python -m app.seed")
    return user


def current_user(
    request: Request,
    db: Session = Depends(get_session),
    audit_session: str | None = Cookie(default=None),
) -> User:
    if get_settings().auth_disabled:
        return _bypass_user(db)
    token = audit_session
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "You are signed out. Sign in to continue.")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is not active. Ask an admin to restore it.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can do this.")
    return user


def user_can_access(db: Session, user: User, client_id: uuid.UUID) -> bool:
    if user.role == Role.admin:
        return True
    row = db.execute(
        select(UserClient).where(UserClient.user_id == user.id, UserClient.client_id == client_id)
    ).first()
    return row is not None


def client_db(
    client_id: uuid.UUID,
    user: User = Depends(current_user),
) -> Iterator[Session]:
    """A session bound to ``client_id`` after checking the user may access it.

    All client-scoped routes take ``client_id`` in the path and depend on this.
    Returns 404 (not 403) for clients the user can't see, so existence isn't leaked.
    """
    db = SessionLocal()
    try:
        client = db.get(Client, client_id)
        if client is None or not user_can_access(db, user, client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found.")
        bind_client(db, client_id)
        db.info["user_id"] = user.id
        yield db
    finally:
        db.close()
