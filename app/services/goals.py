from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Goal, User
from app.services.jobs import enqueue_job
from app.timeutil import user_today


def get_owned_goal(db: Session, goal_id: int, user_id: int) -> Goal:
    goal = db.scalar(
        select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id, Goal.deleted_at.is_(None))
    )
    if not goal:
        raise AppError("NOT_FOUND", "目标不存在", 404)
    return goal


def create_goal(
    db: Session,
    user: User,
    *,
    title: str,
    plan_start_date,
    plan_end_date,
    note: str | None,
) -> tuple[Goal, int]:
    if plan_end_date < plan_start_date:
        raise AppError("VALIDATION_ERROR", "完成日不能早于开始日", 422)
    goal = Goal(
        user_id=user.id,
        title=title.strip(),
        note=note,
        plan_start_date=plan_start_date,
        plan_end_date=plan_end_date,
        status="draft",
    )
    db.add(goal)
    db.flush()
    job = enqueue_job(db, job_type="wbs_generate", user_id=user.id, goal_id=goal.id)
    return goal, job.id


def list_goals(db: Session, user_id: int) -> list[Goal]:
    return list(
        db.scalars(
            select(Goal)
            .where(
                Goal.user_id == user_id,
                Goal.deleted_at.is_(None),
                Goal.status.in_(("active", "planning")),
            )
            .order_by(Goal.updated_at.desc())
        ).all()
    )


def patch_goal(db: Session, goal: Goal, *, title: str | None, note: str | None) -> Goal:
    if title is not None:
        goal.title = title.strip()
    if note is not None:
        goal.note = note
    goal.updated_at = datetime.utcnow()
    return goal


def archive_goal(db: Session, goal: Goal) -> Goal:
    goal.status = "cancelled"
    goal.deleted_at = datetime.utcnow()
    goal.updated_at = goal.deleted_at
    return goal


def plan_edit(
    db: Session,
    user: User,
    goal: Goal,
    *,
    new_plan_end_date,
    note: str | None,
) -> tuple[Goal, int]:
    if goal.status not in ("active", "planning"):
        raise AppError("GOAL_NOT_ACTIVE", "当前状态不可编辑计划", 422)
    if new_plan_end_date is None and note is None:
        raise AppError("VALIDATION_ERROR", "请至少修改完成日或备注", 422)

    today = user_today(user.timezone)
    if new_plan_end_date is not None:
        if new_plan_end_date <= goal.plan_end_date:
            raise AppError("DEADLINE_NOT_LATER", "新完成日必须严格晚于当前完成日", 422)
        if new_plan_end_date < today + timedelta(days=3):
            raise AppError("DEADLINE_TOO_SOON", "新完成日须 ≥ 今天+3天", 422)
        goal.plan_end_date = new_plan_end_date
    if note is not None:
        goal.note = note
    goal.updated_at = datetime.utcnow()
    job = enqueue_job(db, job_type="deadline_replan", user_id=user.id, goal_id=goal.id)
    return goal, job.id


def goal_list_item(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "title": goal.title,
        "status": goal.status,
        "plan_start_date": goal.plan_start_date.isoformat(),
        "plan_end_date": goal.plan_end_date.isoformat(),
        "overall_progress_pct": goal.overall_progress_pct,
        "updated_at": goal.updated_at.isoformat() + "Z" if goal.updated_at else None,
    }


def goal_detail(goal: Goal) -> dict:
    return {
        **goal_list_item(goal),
        "note": goal.note,
        "active_wbs_generation_id": goal.active_wbs_generation_id,
    }
