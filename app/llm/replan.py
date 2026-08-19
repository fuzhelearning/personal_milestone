"""规则重排：明天到 plan_end 按里程碑/任务 sort_order 一天一件，不轮转、不调模型。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DayAssignment, Goal, TaskNode


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def replan_future_assignments(db: Session, goal: Goal, today: date) -> int:
    """删除 tomorrow+ 安排后，按 sort_order 一天一件铺排；今日及历史不动；不改 task_nodes 起止。"""
    if not goal.active_wbs_generation_id:
        return 0

    milestones = list(
        db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == goal.active_wbs_generation_id,
                TaskNode.kind == "milestone",
            )
        ).all()
    )
    mil_order = {m.id: m.sort_order for m in milestones}

    tasks = list(
        db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == goal.active_wbs_generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    )
    if not tasks:
        return 0

    tasks.sort(key=lambda t: (mil_order.get(t.parent_id or 0, 0), t.sort_order, t.id))

    future = db.scalars(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.plan_date > today,
        )
    ).all()
    for a in future:
        db.delete(a)
    db.flush()

    tomorrow = today + timedelta(days=1)
    if tomorrow > goal.plan_end_date:
        return 0
    days = list(_daterange(tomorrow, goal.plan_end_date))
    active_tasks = [t for t in tasks if t.progress_pct < 100] or list(tasks)

    n = 0
    for i, d in enumerate(days):
        if i >= len(active_tasks):
            break
        task = active_tasks[i]
        exists = db.scalar(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id == task.id,
                DayAssignment.plan_date == d,
            )
        )
        if exists:
            continue
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=task.id,
                plan_date=d,
                source="deadline_replan",
                sort_order=i,
            )
        )
        n += 1
    db.flush()
    return n
