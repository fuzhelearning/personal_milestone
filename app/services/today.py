from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DayAssignment, DayEntry, Goal, User
from app.timeutil import user_today


def _get_today_assignment(db: Session, goal: Goal, task_id: int, today) -> DayAssignment:
    a = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == task_id,
            DayAssignment.plan_date == today,
        )
    )
    if not a:
        raise AppError("NOT_FOUND", "今日无该任务安排", 404)
    return a


def _get_or_create_entry(db: Session, goal: Goal, task_id: int, today) -> DayEntry:
    e = db.scalar(
        select(DayEntry).where(DayEntry.task_id == task_id, DayEntry.work_date == today)
    )
    if e:
        return e
    e = DayEntry(
        goal_id=goal.id,
        user_id=goal.user_id,
        task_id=task_id,
        work_date=today,
        status="pending",
    )
    db.add(e)
    db.flush()
    return e


def complete_today(db: Session, user: User, goal: Goal, task_id: int) -> dict:
    today = user_today(user.timezone)
    _get_today_assignment(db, goal, task_id, today)
    e = _get_or_create_entry(db, goal, task_id, today)
    e.status = "done"
    e.incomplete_reason = None
    e.updated_at = datetime.utcnow()
    return {"task_id": task_id, "work_date": today.isoformat(), "status": "done"}


def uncomplete_today(db: Session, user: User, goal: Goal, task_id: int) -> dict:
    today = user_today(user.timezone)
    _get_today_assignment(db, goal, task_id, today)
    e = _get_or_create_entry(db, goal, task_id, today)
    e.status = "pending"
    e.incomplete_reason = None
    e.updated_at = datetime.utcnow()
    return {"task_id": task_id, "work_date": today.isoformat(), "status": "pending"}


def incomplete_today(
    db: Session, user: User, goal: Goal, task_id: int, reason: str
) -> dict:
    """只写当日 DayEntry；顺延留给非周日 day_close（周日 sunday_replan）。"""
    today = user_today(user.timezone)
    _get_today_assignment(db, goal, task_id, today)
    e = _get_or_create_entry(db, goal, task_id, today)
    cleaned = (reason or "").strip()
    if not cleaned:
        raise AppError("ENTRY_INVALID", "请填写未完成原因", 422)
    if e.status == "done":
        raise AppError("ENTRY_INVALID", "已完成的任务请先取消勾选再标记未完成", 422)
    e.status = "not_done"
    e.incomplete_reason = cleaned
    e.updated_at = datetime.utcnow()

    return {
        "task_id": task_id,
        "work_date": today.isoformat(),
        "status": "not_done",
        "incomplete_reason": e.incomplete_reason,
    }
