from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import User
from app.schemas import LoginOut, UserOut, WechatLoginIn
from app.security import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/wechat/login", response_model=LoginOut)
def wechat_login(body: WechatLoginIn, db: Session = Depends(get_db)) -> LoginOut:
    settings = get_settings()
    if not settings.wechat_mock:
        raise AppError("VALIDATION_ERROR", "真实微信登录尚未接入，请开启 WECHAT_MOCK", 422)

    openid = f"mock_{body.code}" if body.code else "mock_anonymous"
    user = db.scalar(select(User).where(User.openid == openid))
    if not user:
        user = User(openid=openid, nickname="Mock User", timezone="Asia/Shanghai")
        db.add(user)
        db.commit()
        db.refresh(user)
    token, expires = create_access_token(user.id)
    return LoginOut(
        access_token=token,
        expires_in=expires,
        user=UserOut(
            id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            timezone=user.timezone,
        ),
    )
