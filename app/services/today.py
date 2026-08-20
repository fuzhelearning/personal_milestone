from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DayAssignment, DayEntry, Goal, User
from app.services.jobs import enqueue_job
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
    today = user_today(user.timezone)
    _get_today_assignment(db, goal, task_id, today)
    e = _get_or_create_entry(db, goal, task_id, today)
    if e.status == "done":
        raise AppError("ENTRY_INVALID", "已完成的任务请先取消勾选再标记未完成", 422)
    e.status = "not_done"
    e.incomplete_reason = reason.strip()
    e.updated_at = datetime.utcnow()

    defer_job_id = None
    # 非周日：经 Celery defer_stack 叠到明天；周日交给 day_close 新计划
    if today.weekday() != 6:
        job = enqueue_job(
            db,
            job_type="defer_stack",
            user_id=user.id,
            goal_id=goal.id,
            result_ref_json={"task_id": task_id, "work_date": today.isoformat()},
        )
        defer_job_id = job.id

    return {
        "task_id": task_id,
        "work_date": today.isoformat(),
        "status": "not_done",
        "incomplete_reason": e.incomplete_reason,
        "defer_job_id": defer_job_id,
    }


def apply_defer_stack(db: Session, goal: Goal, task_id: int, work_date: date) -> date:
    """Idempotently stack assignment onto the day after work_date. Returns target date."""
    tomorrow = work_date + timedelta(days=1)
    exists = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == task_id,
            DayAssignment.plan_date == tomorrow,
        )
    )
    if not exists:
        max_sort = db.scalar(
            select(DayAssignment.sort_order)
            .where(DayAssignment.goal_id == goal.id, DayAssignment.plan_date == tomorrow)
            .order_by(DayAssignment.sort_order.desc())
            .limit(1)
        )
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=task_id,
                plan_date=tomorrow,
                source="defer",
                sort_order=(max_sort or 0) + 1,
            )
        )
        db.flush()
    return tomorrow
