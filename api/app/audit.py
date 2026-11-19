"""Audit log helper. Records who viewed, edited, exported or deleted what.

Never put invoice contents in ``detail``: only ids, field names and counts.
"""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    db: Session,
    *,
    action: str,
    object_type: str,
    object_id: str | uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    detail: dict | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            client_id=client_id or db.info.get("client_id"),
            user_id=user_id or db.info.get("user_id"),
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id else None,
            detail=detail or {},
            ip=request.client.host if request and request.client else None,
        )
    )
    if commit:
        db.commit()
