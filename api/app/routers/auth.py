from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, ratelimit
from ..config import get_settings
from ..deps import COOKIE_NAME, current_user, get_session
from ..models import User
from ..schemas import LoginIn, UserOut
from ..security import create_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_session)):
    ip = request.client.host if request.client else "?"
    keys = [f"email:{body.email.lower()}", f"ip:{ip}"]
    wait = max(ratelimit.is_blocked(k) for k in keys)
    if wait:
        audit.record(db, action="login_blocked", object_type="user", request=request)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many sign-in attempts. Wait {max(1, wait // 60)} minute(s) and try again.",
                            headers={"Retry-After": str(wait)})
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        for k in keys:
            ratelimit.record_failure(k)
        audit.record(db, action="login_failed", object_type="user", detail={"email_domain": body.email.split("@")[-1]}, request=request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That email and password don't match. Check both and try again.")
    ratelimit.reset(keys[0])
    token = create_token(user.id, user.role.value)
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=s.cookie_secure, samesite="strict",
        max_age=s.jwt_ttl_minutes * 60, path="/",
    )
    audit.record(db, action="login", object_type="user", object_id=user.id, user_id=user.id, request=request)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
