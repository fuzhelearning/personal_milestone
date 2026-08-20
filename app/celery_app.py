"""Celery application: RabbitMQ broker, Beat schedules, job tasks."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery = Celery("personal_milestone", broker=settings.celery_broker_url)

# Result backend optional; Job table is the client-visible status source.
if (settings.celery_result_backend or "").strip():
    celery.conf.result_backend = settings.celery_result_backend.strip()

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "day-close-daily": {
            "task": "app.celery_app.day_close_task",
            "schedule": crontab(hour=23, minute=50),
        },
        "llm-timeout-sweep": {
            "task": "app.celery_app.llm_timeout_sweep_task",
            "schedule": 300.0,
        },
    },
)

if settings.celery_task_always_eager:
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True


@celery.task(
    bind=True,
    name="app.celery_app.process_job_task",
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_job_task(self, job_id: int) -> None:
    """Execute a DB Job; LLM/defer retries up to 3 times with exponential backoff (R-b)."""
    from app.db import SessionLocal
    from app.models import Job
    from app.services.jobs import process_job

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        if job.status == "succeeded":
            return
        process_job(db, job)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery.task(name="app.celery_app.day_close_task")
def day_close_task() -> dict:
    """Beat: Asia/Shanghai 23:50 — no Celery auto-retry (F3)."""
    from app.db import SessionLocal
    from app.services.day_close import run_day_close

    db = SessionLocal()
    try:
        result = run_day_close(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery.task(name="app.celery_app.llm_timeout_sweep_task")
def llm_timeout_sweep_task() -> dict:
    """Beat: every 5 minutes — mark stale running LLM jobs failed."""
    from app.db import SessionLocal
    from app.services.jobs import sweep_stale_llm_jobs

    db = SessionLocal()
    try:
        result = sweep_stale_llm_jobs(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
