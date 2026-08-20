"""Celery enqueue (T2) and Beat schedule smoke checks."""

from __future__ import annotations

from unittest.mock import patch

from celery.schedules import crontab
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery
from app.models import Job
from app.services.jobs import _mark_dispatch_failed, enqueue_job
from tests.conftest import make_goal


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
