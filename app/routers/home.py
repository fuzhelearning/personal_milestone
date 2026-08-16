from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.home import build_home

router = APIRouter(prefix="/api/v1", tags=["home"])


@router.get("/home")
def home(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return build_home(db, user)
