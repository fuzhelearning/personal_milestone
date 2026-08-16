from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import InternalRunIn
from app.security import require_internal
from app.services.day_close import run_day_close

router = APIRouter(prefix="/internal/jobs", tags=["internal"])


@router.post("/day-close/run")
def day_close_run(
    body: InternalRunIn | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_internal),
) -> dict:
    as_of = body.as_of if body else None
    result = run_day_close(db, as_of=as_of)
    db.commit()
    return result
