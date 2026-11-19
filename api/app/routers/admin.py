import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, maintenance
from ..deps import client_db, get_session, require_admin
from ..models import AuditLog, Client, User
from .flags import admin_only

router = APIRouter(tags=["admin"])


@router.get("/admin/audit-log")
def audit_log(client_id: uuid.UUID | None = None, action: str | None = None, limit: int = 50, offset: int = 0,
              _: User = Depends(require_admin), db: Session = Depends(get_session)):
    q = select(AuditLog)
    if client_id:
        q = q.where(AuditLog.client_id == client_id)
    if action:
        q = q.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))).all()
    users = {u.id: u.name for u in db.scalars(select(User))}
    clients = {c.id: c.name for c in db.scalars(select(Client))}
    return {"total": total, "rows": [
        {"id": str(r.id), "created_at": r.created_at, "user_name": users.get(r.user_id), "client_name": clients.get(r.client_id) or r.detail.get("client_name"),
         "action": r.action, "object_type": r.object_type, "object_id": r.object_id, "detail": r.detail, "ip": r.ip} for r in rows]}


@router.post("/clients/{client_id}/audit-complete")
def audit_complete(client_id: uuid.UUID, request: Request, _: User = Depends(admin_only), db: Session = Depends(client_db)):
    c = db.get(Client, client_id)
    c.audit_completed_at = datetime.now(timezone.utc)
    db.commit()
    audit.record(db, action="edit", object_type="client", object_id=c.id, detail={"op": "audit_complete"}, request=request)
    return {"audit_completed_at": c.audit_completed_at}


class Confirm(BaseModel):
    confirm: str


@router.post("/clients/{client_id}/delete-raw-files")
def delete_raw(client_id: uuid.UUID, body: Confirm, request: Request, admin: User = Depends(admin_only), db: Session = Depends(client_db)):
    if body.confirm != "DELETE":
        raise HTTPException(422, "Type DELETE to confirm. Nothing was deleted.")
    n = maintenance.delete_raw_files(client_id, user_id=admin.id, reason="manual")
    return {"deleted_objects": n}


@router.post("/clients/{client_id}/delete-everything")
def delete_everything(client_id: uuid.UUID, body: Confirm, request: Request, admin: User = Depends(admin_only), db: Session = Depends(client_db)):
    c = db.get(Client, client_id)
    if body.confirm != c.name:
        raise HTTPException(422, "Type the client's exact name to confirm. Nothing was deleted.")
    maintenance.delete_everything(client_id, user_id=admin.id)
    return {"deleted": True}
