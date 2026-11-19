from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..deps import get_session, require_admin
from ..models import Client, User, UserClient
from ..schemas import UserCreate, UserOut
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    return db.scalars(select(User).order_by(User.name)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Someone already uses that email. Use a different one or edit the existing person.")
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    for cid in body.client_ids:
        if not db.get(Client, cid):
            raise HTTPException(422, "One of the selected clients no longer exists. Refresh and try again.")
        db.add(UserClient(user_id=user.id, client_id=cid))
    db.commit()
    audit.record(db, action="create", object_type="user", object_id=user.id, user_id=admin.id, request=request)
    return user
