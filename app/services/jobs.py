from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.llm.generate import run_wbs_generate
from app.llm.replan import replan_future_assignments
from app.models import Goal, Job, LlmCallLog, User
from app.timeutil import user_today


BUSY_TYPES = ("wbs_generate", "deadline_replan", "sunday_replan", "note_replan")
LLM_RUNNING_TIMEOUT_SECONDS = 150


def _utcnow() -> datetime:
    return datetime.utcnow()


def assert_goal_not_busy(db: Session, goal_id: int) -> None:
    busy = db.scalar(
        select(Job).where(
            Job.goal_id == goal_id,
            Job.type.in_(BUSY_TYPES),
            Job.status.in_(("queued", "running")),
        )
    )
    if busy:
        raise AppError("LLM_BUSY", "该目标已有生成/重排任务进行中", 409)


def enqueue_job(
    db: Session,
    *,
    job_type: str,
    user_id: int | None,
    goal_id: int | None,
    process_now: bool = True,
) -> Job:
    if goal_id and job_type in BUSY_TYPES:
        assert_goal_not_busy(db, goal_id)
    job = Job(
        user_id=user_id,
        goal_id=goal_id,
        type=job_type,
        status="queued",
    )
    db.add(job)
    db.flush()
    if process_now:
        try:
            process_job(db, job)
        except AppError:
            # job 已标记 failed，接口仍可返回 job_id 供轮询
            pass
        except Exception:
            pass
    return job


def process_job(db: Session, job: Job) -> None:
    job.status = "running"
    job.updated_at = _utcnow()
    db.flush()
    try:
        if job.type == "wbs_generate":
            _run_wbs_generate(db, job)
        elif job.type in ("deadline_replan", "sunday_replan", "note_replan"):
            _run_replan(db, job)
        elif job.type == "defer_stack":
            job.result_ref_json = {"deferred": True}
        else:
            raise ValueError(f"unknown job type: {job.type}")
        job.status = "succeeded"
        job.finished_at = _utcnow()
        job.updated_at = job.finished_at
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = _utcnow()
        job.updated_at = job.finished_at
        raise


def _run_wbs_generate(db: Session, job: Job) -> None:
    goal = db.get(Goal, job.goal_id)
    if not goal:
        raise AppError("NOT_FOUND", "目标不存在", 404)
    gen = run_wbs_generate(db, goal)
    job.result_ref_json = {"generation_id": gen.id}
    if gen.status == "failed":
        log = db.get(LlmCallLog, gen.llm_call_id) if gen.llm_call_id else None
        detail = (log.error_message if log and log.error_message else "").strip()
        raise AppError("LLM_FAILED", detail or "WBS 生成失败", 502)


def _run_replan(db: Session, job: Job) -> None:
    goal = db.get(Goal, job.goal_id)
    if not goal:
        raise AppError("NOT_FOUND", "目标不存在", 404)
    user = db.get(User, goal.user_id)
    today = user_today(user.timezone if user else "Asia/Shanghai")
    n = replan_future_assignments(db, goal, today)
    job.result_ref_json = {"replanned_assignments": n}


def sweep_stale_llm_jobs(db: Session) -> dict:
    """将 running 超过阈值的 Job 标为 failed（llm_timeout_sweep）。"""
    cutoff = _utcnow() - timedelta(seconds=LLM_RUNNING_TIMEOUT_SECONDS)
    stale = list(
        db.scalars(
            select(Job).where(
                Job.status == "running",
                Job.updated_at < cutoff,
            )
        ).all()
    )
    for job in stale:
        job.status = "failed"
        job.error_message = f"running 超时（>{LLM_RUNNING_TIMEOUT_SECONDS}s）"
        job.finished_at = _utcnow()
        job.updated_at = job.finished_at
    return {"accepted": True, "processed": len(stale), "skipped": 0}


def get_job_for_user(db: Session, job_id: int, user_id: int) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    if not job:
        raise AppError("NOT_FOUND", "任务不存在", 404)
    return job


def job_to_dict(job: Job) -> dict:
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "error": job.error_message,
        "result_ref": job.result_ref_json,
        "created_at": job.created_at.isoformat() + "Z" if job.created_at else None,
        "finished_at": job.finished_at.isoformat() + "Z" if job.finished_at else None,
    }
