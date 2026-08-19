from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.llm.generate import run_wbs_generate
from app.llm.replan_run import run_llm_replan
from app.models import DeadlineChange, Goal, Job, LlmCallLog, User
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
    deadline_change_id: int | None = None,
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
    if deadline_change_id:
        change = db.get(DeadlineChange, deadline_change_id)
        if change:
            change.job_id = job.id
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
    if not user:
        raise AppError("NOT_FOUND", "用户不存在", 404)
    today = user_today(user.timezone)

    new_plan_end_date = goal.plan_end_date
    deadline_change_id: int | None = None
    if job.type == "deadline_replan":
        change = db.scalar(
            select(DeadlineChange).where(
                DeadlineChange.job_id == job.id,
                DeadlineChange.goal_id == goal.id,
            )
        )
        if change:
            deadline_change_id = change.id
            new_plan_end_date = change.new_end_date

    result = run_llm_replan(
        db,
        goal,
        user,
        today,
        job_type=job.type,
        new_plan_end_date=new_plan_end_date,
        deadline_change_id=deadline_change_id,
    )

    if job.type == "sunday_replan":
        if isinstance(result, dict):
            job.result_ref_json = {
                "applied": result.get("applied", True),
                "suggested_deadline_change": result.get("suggested_deadline_change"),
                "assignment_count": result.get("assignment_count", 0),
                "llm_call_id": result.get("llm_call_id"),
            }
        return

    gen = result
    job.result_ref_json = _deadline_replan_result_ref(gen, deadline_change_id)


def _deadline_replan_result_ref(gen, deadline_change_id: int | None) -> dict:
    ref: dict = {
        "generation_id": gen.id,
        "deadline_change_id": deadline_change_id,
        "confirmable": _confirmable_from_gen(gen),
    }
    if gen.raw_response:
        try:
            data = json.loads(gen.raw_response)
            for key in (
                "requested_plan_end_date",
                "suggested_plan_end_date",
                "current_plan_end_date",
                "deadline_adjustment",
                "suggested_deadline_change",
            ):
                if key in data and data[key] is not None:
                    ref[key] = data[key]
        except (json.JSONDecodeError, TypeError):
            pass
    if "suggested_deadline_change" not in ref:
        val = _suggested_deadline_from_gen(gen)
        if val:
            ref["suggested_deadline_change"] = val
    return ref


def _suggested_deadline_from_gen(gen) -> str | None:
    if not gen.raw_response:
        return None
    try:
        import json

        data = json.loads(gen.raw_response)
        val = data.get("suggested_deadline_change")
        return str(val) if val else None
    except (json.JSONDecodeError, TypeError):
        return None


def _confirmable_from_gen(gen) -> bool:
    from app.llm.replan_persist import generation_confirmable

    return generation_confirmable(gen)


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
