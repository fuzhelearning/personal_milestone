from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.gantt import build_gantt

router = APIRouter(prefix="/api/v1", tags=["gantt"])


@router.get("/gantt")
def gantt(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    goal_id: int | None = None,
) -> dict:
    return build_gantt(db, user, from_date=from_, to_date=to, goal_id=goal_id)
