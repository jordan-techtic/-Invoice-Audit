"""Data deletion: raw files after the retention period, on demand, or everything for a client.

Raw files = the original uploads and the page images made from them (both under clients/<id>/ in storage).
Extracted data, flags and reports are kept unless the admin chooses 'delete everything'. Reports (and their PDFs)
live under reports/<id>/ so deleting raw files never removes them.

  python -m app.maintenance          run the retention check once
  python -m app.maintenance --loop   run it every hour (the 'maintenance' compose service)
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from . import storage
from .audit import record
from .config import get_settings
from .db import system_session
from .models import Client, Upload

log = logging.getLogger("audit.maintenance")


def delete_raw_files(client_id: uuid.UUID, *, user_id: uuid.UUID | None, reason: str) -> int:
    """Delete originals and page images. Returns number of stored objects removed."""
    with system_session() as db:
        client = db.get(Client, client_id)
        if client is None:
            return 0
        n = storage.delete_prefix(storage.client_prefix(client_id))
        now = datetime.now(timezone.utc)
        db.execute(update(Upload).where(Upload.client_id == client_id).values(storage_key=None, raw_deleted_at=now))
        client.raw_files_deleted_at = now
        record(db, action="delete", object_type="raw_files", object_id=client_id, user_id=user_id, client_id=client_id,
               detail={"objects": n, "reason": reason}, commit=False)
        db.commit()
    log.info("raw files deleted for client %s (%s): %d objects", client_id, reason, n)
    return n


def delete_everything(client_id: uuid.UUID, *, user_id: uuid.UUID | None) -> None:
    with system_session() as db:
        client = db.get(Client, client_id)
        if client is None:
            return
        name = client.name
        storage.delete_prefix(storage.client_prefix(client_id))
        storage.delete_prefix(f"reports/{client_id}/")
        # audit row is written first with no client link, then the client and all of its rows are removed (DB cascades)
        record(db, action="delete", object_type="client", object_id=client_id, user_id=user_id, client_id=None,
               detail={"scope": "everything", "client_name": name}, commit=False)
        db.delete(client)
        db.commit()


def run_retention(now: datetime | None = None) -> list[uuid.UUID]:
    """Delete raw files for every client whose audit was completed more than its retention period ago."""
    now = now or datetime.now(timezone.utc)
    default_days = get_settings().raw_file_retention_days
    due: list[uuid.UUID] = []
    with system_session() as db:
        for c in db.scalars(select(Client).where(Client.audit_completed_at.is_not(None), Client.raw_files_deleted_at.is_(None))):
            days = int((c.settings or {}).get("raw_retention_days", default_days))
            if c.audit_completed_at + timedelta(days=days) <= now:
                due.append(c.id)
    for cid in due:
        delete_raw_files(cid, user_id=None, reason="retention_schedule")
    return due


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if "--loop" in sys.argv:
        while True:
            try:
                run_retention()
            except Exception as e:  # noqa: BLE001
                log.error("retention run failed: %s", type(e).__name__)
            time.sleep(3600)
    else:
        print(f"deleted raw files for {len(run_retention())} client(s)")
