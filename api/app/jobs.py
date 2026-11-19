"""RQ job entrypoints. Workers import this module: ``rq worker extraction``."""

from .services.pipeline import process_upload  # noqa: F401


def run_flags(client_id: str, run_id: str) -> None:
    import logging
    import uuid
    from datetime import datetime, timezone

    from .db import client_session
    from .flags.engine import run_flag_engine
    from .models import FlagRun

    with client_session(uuid.UUID(client_id)) as db:
        run = db.get(FlagRun, uuid.UUID(run_id))
        run.status, run.started_at = "running", datetime.now(timezone.utc)
        db.commit()
        try:
            run_flag_engine(db, run)
            run.status = "done"
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logging.getLogger("audit.flags").error("flag run failed: %s", type(e).__name__)
            run = db.get(FlagRun, uuid.UUID(run_id))
            run.status, run.error = "failed", "The checks stopped because of an unexpected error. Run them again; if it repeats, contact support."
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
