from __future__ import annotations

from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DayAssignment, DayEntry, Goal, TaskNode, User
from app.services.assignments import active_task_ids_by_goal
from app.timeutil import user_today, weekday_name, week_sunday


def _display_date(d) -> str:
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    return f"{weekday_name(d)}, {months[d.month - 1]} {d.day}, {d.year}"


def build_home(db: Session, user: User) -> dict:
    today = user_today(user.timezone)
    goals = list(
        db.scalars(
            select(Goal).where(
                Goal.user_id == user.id,
                Goal.deleted_at.is_(None),
                Goal.status.in_(("active", "planning")),
            )
        ).all()
    )
    goal_map = {g.id: g for g in goals}
    goal_ids = list(goal_map.keys())
    active_tasks = active_task_ids_by_goal(db, goals)

    structure_goals = [
        {
            "goal_id": g.id,
            "title": g.title,
            "status": g.status,
            "overall_progress_pct": g.overall_progress_pct,
            "plan_end_date": g.plan_end_date.isoformat(),
            "note": g.note,
        }
        for g in sorted(goals, key=lambda x: x.updated_at, reverse=True)
    ]

    today_tasks: list[dict] = []
    rest: list[dict] = []
    rest_count = 0

    if goal_ids:
        assigns = list(
            db.scalars(
                select(DayAssignment)
                .where(
                    DayAssignment.user_id == user.id,
                    DayAssignment.goal_id.in_(goal_ids),
                    DayAssignment.plan_date >= today,
                    DayAssignment.plan_date <= week_sunday(today),
                )
                .order_by(DayAssignment.plan_date, DayAssignment.sort_order, DayAssignment.id)
            ).all()
        )
        task_ids = {a.task_id for a in assigns}
        tasks = {
            t.id: t
            for t in db.scalars(select(TaskNode).where(TaskNode.id.in_(task_ids))).all()
        } if task_ids else {}
        # milestones for codes
        mil_ids = {t.parent_id for t in tasks.values() if t.parent_id}
        mils = {
            m.id: m
            for m in db.scalars(select(TaskNode).where(TaskNode.id.in_(mil_ids))).all()
        } if mil_ids else {}

        if task_ids:
            entries = {
                (e.task_id, e.work_date): e
                for e in db.scalars(
                    select(DayEntry).where(
                        DayEntry.user_id == user.id,
                        DayEntry.work_date == today,
                        DayEntry.task_id.in_(list(task_ids)),
                    )
                ).all()
            }
        else:
            entries = {}

        by_future: dict = defaultdict(list)
        for a in assigns:
            if a.task_id not in active_tasks.get(a.goal_id, set()):
                continue
            g = goal_map.get(a.goal_id)
            t = tasks.get(a.task_id)
            if not g or not t:
                continue
            mil = mils.get(t.parent_id) if t.parent_id else None
            if a.plan_date == today:
                e = entries.get((a.task_id, today))
                today_tasks.append(
                    {
                        "task_id": t.id,
                        "assignment_id": a.id,
                        "goal_id": g.id,
                        "goal_title": g.title,
                        "title": t.title,
                        "milestone_code": mil.code if mil else None,
                        "milestone_title": mil.title if mil else None,
                        "status": e.status if e else "pending",
                        "incomplete_reason": e.incomplete_reason if e else None,
                    }
                )
            elif a.plan_date > today:
                by_future[a.plan_date].append(
                    {
                        "task_id": t.id,
                        "goal_id": g.id,
                        "goal_title": g.title,
                        "title": t.title,
                        "milestone_code": mil.code if mil else None,
                    }
                )

        for d in sorted(by_future.keys()):
            items = by_future[d]
            rest.append({"date": d.isoformat(), "weekday": weekday_name(d), "items": items})
            rest_count += len(items)

    return {
        "today": {
            "date": today.isoformat(),
            "weekday": weekday_name(today),
            "display": _display_date(today),
            "timezone": user.timezone,
        },
        "structure": {"goals": structure_goals},
        "today_tasks": today_tasks,
        "rest_of_week": rest,
        "rest_of_week_count": rest_count,
    }
