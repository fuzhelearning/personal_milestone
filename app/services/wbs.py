from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DayAssignment, Goal, TaskNode, User, WbsGeneration
from app.timeutil import user_today


def _node_dict(n: TaskNode) -> dict:
    return {
        "id": n.id,
        "code": n.code,
        "title": n.title,
        "kind": n.kind,
        "parent_id": n.parent_id,
        "progress_pct": n.progress_pct,
        "start_date": n.start_date.isoformat() if n.start_date else None,
        "end_date": n.end_date.isoformat() if n.end_date else None,
        "sort_order": n.sort_order,
    }


def get_generation(db: Session, goal: Goal, generation_id: int) -> WbsGeneration:
    gen = db.scalar(
        select(WbsGeneration).where(
            WbsGeneration.id == generation_id,
            WbsGeneration.goal_id == goal.id,
            WbsGeneration.user_id == goal.user_id,
        )
    )
    if not gen:
        raise AppError("NOT_FOUND", "生成记录不存在", 404)
    return gen


def generation_payload(db: Session, gen: WbsGeneration) -> dict:
    nodes = list(
        db.scalars(
            select(TaskNode)
            .where(TaskNode.generation_id == gen.id)
            .order_by(TaskNode.kind.desc(), TaskNode.sort_order, TaskNode.id)
        ).all()
    )
    # milestone 在前
    nodes.sort(key=lambda n: (0 if n.kind == "milestone" else 1, n.sort_order, n.id))
    tasks = {n.id: n for n in nodes if n.kind == "task"}
    if tasks:
        assigns = db.scalars(
            select(DayAssignment)
            .where(DayAssignment.goal_id == gen.goal_id, DayAssignment.task_id.in_(list(tasks.keys())))
            .order_by(DayAssignment.plan_date, DayAssignment.sort_order)
        ).all()
    else:
        assigns = []

    by_date: dict = defaultdict(list)
    for a in assigns:
        t = tasks.get(a.task_id)
        if not t:
            continue
        by_date[a.plan_date.isoformat()].append({"task_code": t.code, "title": t.title})

    preview = [{"date": d, "items": items} for d, items in sorted(by_date.items())]
    return {
        "generation_id": gen.id,
        "status": gen.status,
        "version": gen.version,
        "structure": {"nodes": [_node_dict(n) for n in nodes]},
        "day_assignments_preview": preview,
    }


def confirm_generation(db: Session, user: User, goal: Goal, gen: WbsGeneration) -> dict:
    if gen.status != "suggested":
        raise AppError("VALIDATION_ERROR", "仅 suggested 状态可确认", 422)
    # 旧 active → superseded
    if goal.active_wbs_generation_id:
        old = db.get(WbsGeneration, goal.active_wbs_generation_id)
        if old and old.status == "active":
            old.status = "superseded"
    gen.status = "active"
    gen.confirmed_at = datetime.utcnow()
    goal.active_wbs_generation_id = gen.id
    today = user_today(user.timezone)
    goal.status = "planning" if today < goal.plan_start_date else "active"
    goal.updated_at = datetime.utcnow()
    return {"goal_id": goal.id, "generation_id": gen.id, "status": goal.status}


def structure_payload(db: Session, goal: Goal) -> dict:
    if not goal.active_wbs_generation_id:
        return {"overall_progress_pct": goal.overall_progress_pct, "nodes": []}
    nodes = list(
        db.scalars(
            select(TaskNode)
            .where(TaskNode.generation_id == goal.active_wbs_generation_id)
            .order_by(TaskNode.sort_order, TaskNode.id)
        ).all()
    )
    nodes.sort(key=lambda n: (0 if n.kind == "milestone" else 1, n.sort_order, n.id))
    return {
        "overall_progress_pct": goal.overall_progress_pct,
        "nodes": [_node_dict(n) for n in nodes],
    }
