import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..deps import client_db
from ..models import Upload, UploadSource, UploadStatus
from ..services.ingest import RejectedFile, ingest_file
from ..services.pipeline import retry_upload

router = APIRouter(prefix="/clients/{client_id}/uploads", tags=["uploads"])


def upload_out(u: Upload) -> dict:
    return {
        "id": str(u.id), "filename": u.filename, "status": u.status.value, "status_detail": u.status_detail,
        "source": u.source.value, "size_bytes": u.size_bytes, "page_count": u.page_count,
        "invoice_count": u.invoice_count, "created_at": u.created_at.isoformat(),
        "duplicate_of": str(u.duplicate_of) if u.duplicate_of else None,
    }


@router.post("", status_code=201)
async def upload_files(request: Request, client_id: uuid.UUID, files: list[UploadFile] = File(...), db: Session = Depends(client_db)):
    """Accepts one or more files. Per-file outcome is returned so the UI can say what was skipped and why."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    out = []
    for f in files:
        data = await f.read(limit + 1)
        try:
            up = ingest_file(db, filename=f.filename or "file", data=data, source=UploadSource.web, user_id=db.info["user_id"])
            audit.record(db, action="upload", object_type="upload", object_id=up.id, request=request)
            out.append({"ok": True, "upload": upload_out(up)})
        except RejectedFile as e:
            out.append({"ok": False, "filename": f.filename, "error": str(e)})
    return out


@router.get("")
def list_uploads(client_id: uuid.UUID, db: Session = Depends(client_db)):
    rows = db.scalars(select(Upload).order_by(Upload.created_at.desc()).limit(500)).all()
    return [upload_out(u) for u in rows]


@router.post("/{upload_id}/retry")
def retry(upload_id: uuid.UUID, client_id: uuid.UUID, request: Request, db: Session = Depends(client_db)):
    up = db.get(Upload, upload_id)
    if up is None or up.id is None:
        raise HTTPException(404, "Upload not found.")
    if up.status != UploadStatus.failed:
        raise HTTPException(409, "Only failed files can be retried.")
    retry_upload(db, up)
    audit.record(db, action="edit", object_type="upload", object_id=up.id, detail={"op": "retry"}, request=request)
    db.refresh(up)
    return upload_out(up)
