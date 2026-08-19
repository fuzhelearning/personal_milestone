"""重排上下文：当前目标计划 + 用户跨目标并行负载。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DayAssignment, DayEntry, Goal, TaskNode, User


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def build_replan_context(
    db: Session,
    goal: Goal,
    user: User,
    today: date,
    new_plan_end_date: date,
    *,
    trigger: str = "deadline_replan",
) -> dict:
    """收集重排 prompt 所需上下文（含 defer、remaining_days、跨目标负载）。"""
    _ = trigger
    tomorrow = today + timedelta(days=1)
    window_end = new_plan_end_date

    target = _goal_plan_snapshot(db, goal, today)
    other_goals: list[dict] = []
    cross_goal_daily_load: dict[str, list[dict]] = defaultdict(list)

    active_goals = list(
        db.scalars(
            select(Goal).where(
                Goal.user_id == user.id,
                Goal.deleted_at.is_(None),
                Goal.status.in_(("active", "planning")),
                Goal.active_wbs_generation_id.isnot(None),
            )
        ).all()
    )
    for g in active_goals:
        snap = _goal_schedule_in_window(db, g, tomorrow, window_end)
        if not snap["day_schedule"]:
            continue
        entry = {
            "goal_id": g.id,
            "goal_title": g.title,
            "is_target": g.id == goal.id,
            "day_schedule": snap["day_schedule"],
        }
        if g.id != goal.id:
            other_goals.append(entry)
        for row in snap["day_schedule"]:
            cross_goal_daily_load[row["date"]].append(
                {
                    "goal_id": g.id,
                    "goal_title": g.title,
                    "task_id": row.get("task_id"),
                    "task_code": row["task_code"],
                    "task_title": row["task_title"],
                    "is_target": g.id == goal.id,
                }
            )

    goal_json = {
        "id": goal.id,
        "title": goal.title,
        "plan_start_date": goal.plan_start_date.isoformat(),
        "plan_end_date": goal.plan_end_date.isoformat(),
    }
    active_plan_json = {
        "past_assignments": target["past_assignments"],
        "future_assignments": target["future_assignments"],
        "milestones": target["milestones"],
    }
    task_status_json = target["task_status"]
    open_tasks_json = [t for t in task_status_json if t["status"] != "completed"]
    done_summary_json = target["done_summary"]
    future_assignments_json = target["future_assignments"]

    return {
        "today": today.isoformat(),
        "tomorrow": tomorrow.isoformat(),
        "new_plan_end_date": new_plan_end_date.isoformat(),
        "replan_day_count": max(0, (new_plan_end_date - tomorrow).days + 1),
        "current_plan_end_date": goal.plan_end_date.isoformat(),
        "target_goal": target,
        "other_goals_schedule": other_goals,
        "all_goals_by_date": dict(sorted(cross_goal_daily_load.items())),
        "cross_goal_daily_load_json": dict(sorted(cross_goal_daily_load.items())),
        "goal_json": goal_json,
        "active_plan_json": active_plan_json,
        "task_status_json": task_status_json,
        "open_tasks_json": open_tasks_json,
        "done_summary_json": done_summary_json,
        "future_assignments_json": future_assignments_json,
    }


# 兼容旧名
gather_replan_context = build_replan_context


def _goal_plan_snapshot(db: Session, goal: Goal, today: date) -> dict:
    if not goal.active_wbs_generation_id:
        return {
            "goal_id": goal.id,
            "title": goal.title,
            "milestones": [],
            "tasks": [],
            "completed_tasks": [],
            "incomplete_tasks": [],
            "task_status": [],
            "done_summary": [],
            "past_assignments": [],
            "future_assignments": [],
        }

    nodes = list(
        db.scalars(
            select(TaskNode).where(TaskNode.generation_id == goal.active_wbs_generation_id)
        ).all()
    )
    milestones = [n for n in nodes if n.kind == "milestone"]
    tasks = [n for n in nodes if n.kind == "task"]
    mil_by_id = {m.id: m for m in milestones}

    task_rows = []
    task_status: list[dict] = []
    completed: list[str] = []
    incomplete: list[str] = []
    done_summary: list[dict] = []

    for t in sorted(tasks, key=lambda x: (x.sort_order, x.id)):
        mil = mil_by_id.get(t.parent_id or 0)
        is_done = t.progress_pct >= 100
        status = "completed" if is_done else ("in_progress" if t.progress_pct > 0 else "not_started")
        remaining_days = _remaining_days(db, goal, t, today) if not is_done else 0
        row = {
            "id": t.id,
            "code": t.code,
            "title": t.title,
            "milestone_code": mil.code if mil else None,
            "milestone_title": mil.title if mil else None,
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "end_date": t.end_date.isoformat() if t.end_date else None,
            "progress_pct": t.progress_pct,
            "status": status,
            "remaining_days": remaining_days,
        }
        task_rows.append(row)
        task_status.append(
            {
                "id": t.id,
                "code": t.code,
                "title": t.title,
                "status": status,
                "remaining_days": remaining_days,
                "progress_pct": t.progress_pct,
            }
        )
        if is_done:
            completed.append(t.code)
            done_summary.append({"code": t.code, "title": t.title, "progress_pct": t.progress_pct})
        else:
            incomplete.append(t.code)

    task_ids = [t.id for t in tasks]
    assigns = []
    if task_ids:
        assigns = list(
            db.scalars(
                select(DayAssignment)
                .where(
                    DayAssignment.goal_id == goal.id,
                    DayAssignment.task_id.in_(task_ids),
                )
                .order_by(DayAssignment.plan_date, DayAssignment.sort_order)
            ).all()
        )
    code_by_id = {t.id: t.code for t in tasks}
    title_by_id = {t.id: t.title for t in tasks}

    past_assignments = []
    future_assignments = []
    for a in assigns:
        code = code_by_id.get(a.task_id, "?")
        entry = db.scalar(
            select(DayEntry).where(
                DayEntry.task_id == a.task_id,
                DayEntry.work_date == a.plan_date,
            )
        )
        item = {
            "date": a.plan_date.isoformat(),
            "task_id": a.task_id,
            "task_code": code,
            "task_title": title_by_id.get(a.task_id, ""),
            "entry_status": entry.status if entry else None,
            "source": a.source,
        }
        if a.plan_date <= today:
            past_assignments.append(item)
        else:
            future_assignments.append(item)

    return {
        "goal_id": goal.id,
        "title": goal.title,
        "milestones": [
            {
                "code": m.code,
                "title": m.title,
                "start_date": m.start_date.isoformat() if m.start_date else None,
                "end_date": m.end_date.isoformat() if m.end_date else None,
                "progress_pct": m.progress_pct,
            }
            for m in sorted(milestones, key=lambda x: (x.sort_order, x.id))
        ],
        "tasks": task_rows,
        "completed_tasks": completed,
        "incomplete_tasks": incomplete,
        "task_status": task_status,
        "done_summary": done_summary,
        "past_assignments": past_assignments,
        "future_assignments": future_assignments,
    }


def _remaining_days(db: Session, goal: Goal, task: TaskNode, today: date) -> int:
    """未完成任务：未来安排天数 + 今日未完成安排。"""
    assigns = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id == task.id,
                DayAssignment.plan_date >= today,
            )
        ).all()
    )
    remaining = 0
    for a in assigns:
        if a.plan_date > today:
            remaining += 1
            continue
        entry = db.scalar(
            select(DayEntry).where(
                DayEntry.task_id == task.id,
                DayEntry.work_date == a.plan_date,
            )
        )
        if not entry or entry.status != "done":
            remaining += 1
    return remaining


def _goal_schedule_in_window(
    db: Session,
    goal: Goal,
    start: date,
    end: date,
) -> dict:
    if not goal.active_wbs_generation_id or start > end:
        return {"day_schedule": []}

    tasks = list(
        db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == goal.active_wbs_generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    )
    if not tasks:
        return {"day_schedule": []}

    code_by_id = {t.id: t.code for t in tasks}
    title_by_id = {t.id: t.title for t in tasks}
    assigns = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date >= start,
                DayAssignment.plan_date <= end,
            )
            .order_by(DayAssignment.plan_date)
        ).all()
    )
    return {
        "day_schedule": [
            {
                "date": a.plan_date.isoformat(),
                "task_id": a.task_id,
                "task_code": code_by_id.get(a.task_id, "?"),
                "task_title": title_by_id.get(a.task_id, ""),
            }
            for a in assigns
        ]
    }
