from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DayAssignment, DayEntry, Goal, TaskNode, User
from app.timeutil import add_days, user_today


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def cell_status(today: date, cell_date: date, task_ids: list[int], entry_map: dict) -> str:
    """ADR-0016."""
    if cell_date > today:
        return "pending"
    statuses = [entry_map.get((tid, cell_date), "pending") for tid in task_ids]
    if statuses and all(s == "done" for s in statuses):
        return "done"
    return "not_done"


def build_gantt(
    db: Session,
    user: User,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    goal_id: int | None = None,
) -> dict:
    today = user_today(user.timezone)
    start = from_date or add_days(today, -30)
    end = to_date or add_days(today, 30)
    dates = [d.isoformat() for d in _daterange(start, end)]

    q = select(Goal).where(
        Goal.user_id == user.id,
        Goal.deleted_at.is_(None),
        Goal.status.in_(("active", "planning")),
    )
    if goal_id is not None:
        q = q.where(Goal.id == goal_id)
    goals = list(db.scalars(q).all())

    out_goals = []
    for g in goals:
        if not g.active_wbs_generation_id:
            out_goals.append(
                {
                    "goal_id": g.id,
                    "title": g.title,
                    "status": g.status,
                    "overall_progress_pct": g.overall_progress_pct,
                    "current_milestone": None,
                    "milestones": [],
                }
            )
            continue

        nodes = list(
            db.scalars(
                select(TaskNode).where(TaskNode.generation_id == g.active_wbs_generation_id)
            ).all()
        )
        milestones = sorted(
            [n for n in nodes if n.kind == "milestone"],
            key=lambda n: (n.sort_order, n.id),
        )
        tasks = [n for n in nodes if n.kind == "task"]
        tasks_by_mil: dict[int, list[TaskNode]] = defaultdict(list)
        task_ids = []
        for t in tasks:
            if t.parent_id:
                tasks_by_mil[t.parent_id].append(t)
            task_ids.append(t.id)

        if task_ids:
            assigns = list(
                db.scalars(
                    select(DayAssignment).where(
                        DayAssignment.goal_id == g.id,
                        DayAssignment.plan_date >= start,
                        DayAssignment.plan_date <= end,
                        DayAssignment.task_id.in_(task_ids),
                    )
                ).all()
            )
        else:
            assigns = []

        assign_by_task_date: dict[tuple[int, date], DayAssignment] = {
            (a.task_id, a.plan_date): a for a in assigns
        }

        entry_rows = (
            db.scalars(
                select(DayEntry).where(
                    DayEntry.goal_id == g.id,
                    DayEntry.work_date >= start,
                    DayEntry.work_date <= end,
                    DayEntry.task_id.in_(task_ids),
                )
            ).all()
            if task_ids
            else []
        )
        entry_map = {(e.task_id, e.work_date): e.status for e in entry_rows}

        current_mil = None
        for m in milestones:
            if m.start_date and m.end_date and m.start_date <= today <= m.end_date:
                current_mil = m
                break
        if current_mil is None and milestones:
            # 尚未开始取第一个未来；已过取最后一个
            future = [m for m in milestones if m.start_date and m.start_date > today]
            past = [m for m in milestones if m.end_date and m.end_date < today]
            current_mil = future[0] if future else (past[-1] if past else milestones[0])

        mil_payload = []
        for m in milestones:
            child_tasks = tasks_by_mil.get(m.id, [])
            child_ids = [t.id for t in child_tasks]
            cells = []
            for d in _daterange(start, end):
                tids = [tid for tid in child_ids if (tid, d) in assign_by_task_date]
                if not tids:
                    continue
                cells.append(
                    {
                        "date": d.isoformat(),
                        "planned": True,
                        "status": cell_status(today, d, tids, entry_map),
                        "task_ids": tids,
                    }
                )
            mil_payload.append(
                {
                    "milestone_id": m.id,
                    "code": m.code,
                    "title": m.title,
                    "start_date": m.start_date.isoformat() if m.start_date else None,
                    "end_date": m.end_date.isoformat() if m.end_date else None,
                    "is_current": current_mil is not None and m.id == current_mil.id,
                    "cells": cells,
                }
            )

        out_goals.append(
            {
                "goal_id": g.id,
                "title": g.title,
                "status": g.status,
                "overall_progress_pct": g.overall_progress_pct,
                "current_milestone": (
                    {
                        "milestone_id": current_mil.id,
                        "code": current_mil.code,
                        "title": current_mil.title,
                        "start_date": current_mil.start_date.isoformat() if current_mil.start_date else None,
                        "end_date": current_mil.end_date.isoformat() if current_mil.end_date else None,
                    }
                    if current_mil
                    else None
                ),
                "milestones": mil_payload,
            }
        )

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "today": today.isoformat(),
        "dates": dates,
        "goals": out_goals,
    }
