from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import User

ALGORITHM = "HS256"


def create_access_token(user_id: int) -> tuple[str, int]:
    settings = get_settings()
    expire_seconds = settings.jwt_expire_seconds
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=expire_seconds),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, expire_seconds


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("UNAUTHORIZED", "未登录或 token 无效", 401)
    token = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise AppError("UNAUTHORIZED", "未登录或 token 无效", 401) from exc
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise AppError("UNAUTHORIZED", "未登录或 token 无效", 401)
    return user


def require_internal(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> None:
    if x_internal_token != get_settings().internal_token:
        raise AppError("UNAUTHORIZED", "内部鉴权失败", 401)
