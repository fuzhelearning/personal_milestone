"""规则重排：不轮转、天数多留空、任务多截断。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.llm.replan import replan_future_assignments
from app.models import DayAssignment
from tests.conftest import make_goal, seed_active_wbs


def test_replan_no_rotation(db, user):
    """连续日期应对应连续 sort_order，而非取模轮转。"""
    today = date(2026, 8, 1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=3)

    n = replan_future_assignments(db, goal, today)
    assert n == 3
    rows = list(
        db.scalars(
            select(DayAssignment)
            .where(DayAssignment.goal_id == goal.id, DayAssignment.plan_date > today)
            .order_by(DayAssignment.plan_date)
        ).all()
    )
    assert [r.task_id for r in rows] == [tasks[0].id, tasks[1].id, tasks[2].id]
    # 若轮转，第 4 天会再出现 tasks[0]；此处天数多于任务时应留空而非轮转
    assert len(rows) == 3


def test_replan_extra_days_left_blank(db, user):
    today = date(2026, 8, 10)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=10))
    tasks = seed_active_wbs(db, goal, task_count=2)
    n = replan_future_assignments(db, goal, today)
    assert n == 2
    rows = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date > today,
            )
        ).all()
    )
    assert len(rows) == 2
    assert {r.task_id for r in rows} == {tasks[0].id, tasks[1].id}


def test_replan_extra_tasks_truncated(db, user):
    today = date(2026, 8, 1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=2))
    tasks = seed_active_wbs(db, goal, task_count=5)
    n = replan_future_assignments(db, goal, today)
    # tomorrow..end = 2 days
    assert n == 2
    rows = list(
        db.scalars(
            select(DayAssignment)
            .where(DayAssignment.goal_id == goal.id, DayAssignment.plan_date > today)
            .order_by(DayAssignment.plan_date)
        ).all()
    )
    assert [r.task_id for r in rows] == [tasks[0].id, tasks[1].id]


def test_replan_preserves_today(db, user):
    today = date(2026, 8, 1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=3))
    tasks = seed_active_wbs(db, goal, task_count=2)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=goal.user_id,
            task_id=tasks[0].id,
            plan_date=today,
            source="ai",
            sort_order=0,
        )
    )
    db.flush()
    replan_future_assignments(db, goal, today)
    today_row = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.plan_date == today,
        )
    )
    assert today_row is not None
    assert today_row.task_id == tasks[0].id
