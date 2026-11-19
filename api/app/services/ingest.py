"""Accept a file into the system: validate, hash, de-duplicate, store, enqueue."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..models import Upload, UploadSource, UploadStatus
from ..queue import enqueue
from ..security import sha256_hex
from .preprocess import sniff_type

CONTENT_TYPES = {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic"}
EXT = {"pdf": ".pdf", "jpeg": ".jpg", "png": ".png", "heic": ".heic"}


class RejectedFile(Exception):
    """Message is safe to show to the user."""


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name.split("/")[-1].split("\\")[-1])[:200] or "file"


def ingest_file(
    db: Session, *, filename: str, data: bytes, source: UploadSource, user_id: uuid.UUID | None = None
) -> Upload:
    """``db`` must be bound to a client. Returns the Upload row (status queued, or duplicate)."""
    s = get_settings()
    name = _safe_name(filename)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise RejectedFile(f"{name} is larger than {s.max_upload_mb} MB. Compress it or split it into smaller files.")
    if not data:
        raise RejectedFile(f"{name} is empty. Check the file and upload it again.")
    kind = sniff_type(data)
    if kind is None:
        raise RejectedFile(f"{name} isn't a PDF, JPG, PNG or HEIC file. Convert it and upload again.")

    digest = sha256_hex(data)
    existing = db.scalar(
        select(Upload).where(Upload.sha256 == digest, Upload.status != UploadStatus.duplicate).order_by(Upload.created_at)
    )
    up = Upload(
        filename=name, content_type=CONTENT_TYPES[kind], size_bytes=len(data), sha256=digest, source=source, uploaded_by=user_id
    )
    if existing:
        up.status = UploadStatus.duplicate
        up.duplicate_of = existing.id
        up.status_detail = f"Skipped: identical to {existing.filename}, already uploaded on {existing.created_at:%b %-d, %Y}."
        db.add(up)
        db.commit()
        return up

    up.id = uuid.uuid4()
    up.storage_key = f"{storage.client_prefix(db.info['client_id'])}{up.id}/original{EXT[kind]}"
    storage.put(up.storage_key, data, CONTENT_TYPES[kind])
    db.add(up)
    db.commit()
    enqueue("extraction", "app.jobs.process_upload", str(db.info["client_id"]), str(up.id))
    db.refresh(up)  # inline mode (tests, offline eval) has already updated the row from another session
    return up
