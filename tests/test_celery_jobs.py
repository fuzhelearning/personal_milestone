"""Celery enqueue (T2) and Beat schedule smoke checks."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery
from app.models import DayAssignment, Job
from app.services.jobs import _mark_dispatch_failed, enqueue_job, process_job
from app.services.today import apply_defer_stack, incomplete_today
from tests.conftest import make_goal, seed_active_wbs


def test_beat_schedule_day_close_and_sweep():
    schedule = celery.conf.beat_schedule
    assert "day-close-daily" in schedule
    assert "llm-timeout-sweep" in schedule
    day_close = schedule["day-close-daily"]["schedule"]
    assert isinstance(day_close, crontab)
    assert day_close.hour == {23}
    assert day_close.minute == {50}
    assert schedule["llm-timeout-sweep"]["schedule"] == 300.0
    assert celery.conf.timezone == "Asia/Shanghai"


def test_enqueue_after_commit_dispatches_celery(db, user):
    goal = make_goal(db, user)
    db.commit()

    with patch("app.services.jobs._dispatch_job_to_celery") as dispatch:
        job = enqueue_job(
            db,
            job_type="wbs_generate",
            user_id=user.id,
            goal_id=goal.id,
            process_now=False,
        )
        assert job.status == "queued"
        dispatch.assert_not_called()
        db.commit()
        dispatch.assert_called_once_with(job.id)


def test_dispatch_failure_marks_job_failed(db, user):
    goal = make_goal(db, user)
    job = enqueue_job(
        db,
        job_type="wbs_generate",
        user_id=user.id,
        goal_id=goal.id,
        process_now=False,
    )
    db.commit()
    job_id = job.id

    TestSession = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, future=True)
    with patch("app.db.SessionLocal", TestSession):
        _mark_dispatch_failed(job_id, "celery dispatch failed: boom")

    row = db.get(Job, job_id)
    db.refresh(row)
    assert row.status == "failed"
    assert "celery dispatch failed" in (row.error_message or "")


def test_defer_stack_via_process_job(db, user):
    today = date(2026, 8, 19)  # Wednesday
    goal = make_goal(db, user, start=today, end=today + timedelta(days=5))
    tasks = seed_active_wbs(db, goal, task_count=1)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=user.id,
            task_id=tasks[0].id,
            plan_date=today,
            source="ai",
            sort_order=0,
        )
    )
    db.flush()

    with patch("app.services.today.user_today", return_value=today):
        result = incomplete_today(db, user, goal, tasks[0].id, "没空")
    assert result["defer_job_id"]

    job = db.get(Job, result["defer_job_id"])
    assert job.type == "defer_stack"
    assert job.status == "queued"

    process_job(db, job)
    assert job.status == "succeeded"
    tomorrow = today + timedelta(days=1)
    stacked = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == tasks[0].id,
            DayAssignment.plan_date == tomorrow,
        )
    )
    assert stacked is not None
    assert stacked.source == "defer"


def test_apply_defer_stack_idempotent(db, user):
    today = date(2026, 8, 19)
    goal = make_goal(db, user, start=today, end=today + timedelta(days=3))
    tasks = seed_active_wbs(db, goal, task_count=1)
    t1 = apply_defer_stack(db, goal, tasks[0].id, today)
    t2 = apply_defer_stack(db, goal, tasks[0].id, today)
    assert t1 == t2 == today + timedelta(days=1)
    rows = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id == tasks[0].id,
                DayAssignment.plan_date == t1,
            )
        ).all()
    )
    assert len(rows) == 1
