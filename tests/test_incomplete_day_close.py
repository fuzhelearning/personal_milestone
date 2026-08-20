"""Incomplete 只写 DayEntry；非周日顺延仅 day_close。"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import DayAssignment, DayEntry, Job
from app.services.assignments import is_execution_defer_source
from app.services.day_close import _close_goal_day
from app.services.jobs import enqueue_job, process_job
from app.services.today import complete_today, incomplete_today
from tests.conftest import make_goal, seed_active_wbs


def _assign_today(db, user, goal, task, today: date, *, source: str = "ai") -> None:
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=user.id,
            task_id=task.id,
            plan_date=today,
            source=source,
            sort_order=0,
        )
    )
    db.flush()


def _tomorrow_assignment(db, goal, task_id: int, tomorrow: date):
    return db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == task_id,
            DayAssignment.plan_date == tomorrow,
        )
    )


def test_incomplete_does_not_stack_next_day(db, user):
    today = date(2026, 8, 19)  # Wednesday
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        result = incomplete_today(db, user, goal, tasks[0].id, "没空")

    assert result["status"] == "not_done"
    assert result["incomplete_reason"] == "没空"
    assert "defer_job_id" not in result
    assert _tomorrow_assignment(db, goal, tasks[0].id, tomorrow) is None
    jobs = list(db.scalars(select(Job).where(Job.goal_id == goal.id)).all())
    assert not any(j.type == "defer_stack" for j in jobs)


def test_incomplete_rejects_blank_reason(db, user):
    today = date(2026, 8, 19)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=3))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        with pytest.raises(AppError) as ei:
            incomplete_today(db, user, goal, tasks[0].id, "   ")
    assert ei.value.code == "ENTRY_INVALID"


def test_incomplete_rejects_when_done(db, user):
    today = date(2026, 8, 19)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=3))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        complete_today(db, user, goal, tasks[0].id)
        with pytest.raises(AppError) as ei:
            incomplete_today(db, user, goal, tasks[0].id, "太晚了")
    assert ei.value.code == "ENTRY_INVALID"


def test_day_close_skips_defer_when_final_done(db, user):
    today = date(2026, 8, 19)  # Wednesday
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        incomplete_today(db, user, goal, tasks[0].id, "先标未完成")
        complete_today(db, user, goal, tasks[0].id)

    _close_goal_day(db, user, goal, today)
    assert _tomorrow_assignment(db, goal, tasks[0].id, tomorrow) is None


def test_day_close_defers_pending_as_not_done(db, user):
    today = date(2026, 8, 19)
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    _close_goal_day(db, user, goal, today)

    entry = db.scalar(
        select(DayEntry).where(DayEntry.task_id == tasks[0].id, DayEntry.work_date == today)
    )
    assert entry is not None
    assert entry.status == "not_done"
    stacked = _tomorrow_assignment(db, goal, tasks[0].id, tomorrow)
    assert stacked is not None
    assert stacked.source == "day_close_defer"
    assert is_execution_defer_source(stacked.source)


def test_day_close_defer_idempotent_when_tomorrow_exists(db, user):
    today = date(2026, 8, 19)
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=user.id,
            task_id=tasks[0].id,
            plan_date=tomorrow,
            source="ai",
            sort_order=0,
        )
    )
    db.flush()

    with patch("app.services.today.user_today", return_value=today):
        incomplete_today(db, user, goal, tasks[0].id, "没空")
    _close_goal_day(db, user, goal, today)

    rows = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id == tasks[0].id,
                DayAssignment.plan_date == tomorrow,
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].source == "ai"


def test_sunday_incomplete_does_not_plus_one_day(db, user):
    today = date(2026, 8, 16)  # Sunday
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=7))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        incomplete_today(db, user, goal, tasks[0].id, "周日未做")

    assert _tomorrow_assignment(db, goal, tasks[0].id, tomorrow) is None

    with patch("app.services.day_close.run_llm_replan") as replan:
        replan.side_effect = Exception("skip llm")
        _close_goal_day(db, user, goal, today)

    # 周日不做简单 +1 天 stack
    assert _tomorrow_assignment(db, goal, tasks[0].id, tomorrow) is None


def test_day_close_writes_day_close_defer_for_manual_not_done(db, user):
    today = date(2026, 8, 19)
    tomorrow = today + timedelta(days=1)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    _assign_today(db, user, goal, tasks[0], today)

    with patch("app.services.today.user_today", return_value=today):
        incomplete_today(db, user, goal, tasks[0].id, "没空")
    _close_goal_day(db, user, goal, today)

    stacked = _tomorrow_assignment(db, goal, tasks[0].id, tomorrow)
    assert stacked is not None
    assert stacked.source == "day_close_defer"


def test_legacy_defer_source_compatible_with_day_close_defer():
    assert is_execution_defer_source("defer")
    assert is_execution_defer_source("day_close_defer")
    assert not is_execution_defer_source("ai")


def test_defer_stack_job_disabled(db, user):
    goal = make_goal(db, user)
    job = enqueue_job(
        db,
        job_type="defer_stack",
        user_id=user.id,
        goal_id=goal.id,
        process_now=False,
        result_ref_json={"task_id": 1, "work_date": "2026-08-19"},
    )
    with pytest.raises(AppError):
        process_job(db, job)
    assert job.status == "failed"
    assert "停用" in (job.error_message or "")
