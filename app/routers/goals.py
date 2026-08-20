from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import DeadlineChange, User
from app.schemas import (
    ConfirmWbsIn,
    DeadlineChangeIn,
    GoalCreateIn,
    GoalPatchIn,
    IncompleteIn,
    PlanEditIn,
)
from app.security import get_current_user
from app.services import goals as goals_svc
from app.services import today as today_svc
from app.services import wbs as wbs_svc
from app.services.jobs import enqueue_job
from app.timeutil import earliest_plan_end, user_today

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


@router.post("")
def create_goal(
    body: GoalCreateIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal, job_id = goals_svc.create_goal(
        db,
        user,
        title=body.title,
        plan_start_date=body.plan_start_date,
        plan_end_date=body.plan_end_date,
        note=body.note,
    )
    db.commit()
    response.status_code = 202
    return {"goal_id": goal.id, "job_id": job_id, "status": goal.status}


@router.get("")
def list_goals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    items = [goals_svc.goal_list_item(g) for g in goals_svc.list_goals(db, user.id)]
    return {"items": items}


@router.get("/{goal_id}")
def get_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return goals_svc.goal_detail(goals_svc.get_owned_goal(db, goal_id, user.id))


@router.patch("/{goal_id}")
def patch_goal(
    goal_id: int,
    body: GoalPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    goals_svc.patch_goal(db, goal, title=body.title, note=body.note)
    db.commit()
    return goals_svc.goal_detail(goal)


@router.post("/{goal_id}/archive")
def archive_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    goals_svc.archive_goal(db, goal)
    db.commit()
    return {"goal_id": goal.id, "status": goal.status}


@router.get("/{goal_id}/wbs/generations/{generation_id}")
def get_wbs_generation(
    goal_id: int,
    generation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    gen = wbs_svc.get_generation(db, goal, generation_id)
    return wbs_svc.generation_payload(db, gen)


@router.post("/{goal_id}/wbs/generations/{generation_id}/cancel")
def cancel_wbs(
    goal_id: int,
    generation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    gen = wbs_svc.get_generation(db, goal, generation_id)
    result = wbs_svc.cancel_generation(db, goal, gen)
    db.commit()
    return result


@router.post("/{goal_id}/wbs/generations/{generation_id}/confirm")
def confirm_wbs(
    goal_id: int,
    generation_id: int,
    body: ConfirmWbsIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ = body
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    gen = wbs_svc.get_generation(db, goal, generation_id)
    result = wbs_svc.confirm_generation(db, user, goal, gen)
    db.commit()
    return result


@router.post("/{goal_id}/wbs/generations")
def regenerate_wbs(
    goal_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    job = enqueue_job(db, job_type="wbs_generate", user_id=user.id, goal_id=goal.id)
    db.commit()
    response.status_code = 202
    gen_id = (job.result_ref_json or {}).get("generation_id") if job.result_ref_json else None
    return {"generation_id": gen_id, "job_id": job.id, "status": job.status}


@router.get("/{goal_id}/structure")
def get_structure(
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    return wbs_svc.structure_payload(db, goal)


@router.post("/{goal_id}/plan-edit")
def plan_edit(
    goal_id: int,
    body: PlanEditIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    goal, job_id, change_id = goals_svc.plan_edit(
        db, user, goal, new_plan_end_date=body.new_plan_end_date, note=body.note
    )
    db.commit()
    today = user_today(user.timezone)
    response.status_code = 202 if job_id else 200
    out = {
        "goal_id": goal.id,
        "status": "queued" if job_id else goal.status,
        "plan_end_date": goal.plan_end_date.isoformat(),
        "note": goal.note,
        "earliest_allowed_date": earliest_plan_end(goal.plan_end_date, today).isoformat(),
    }
    if job_id:
        out["job_id"] = job_id
    if change_id:
        out["change_id"] = change_id
    return out


@router.post("/{goal_id}/today-tasks/{task_id}/complete")
def complete_task(
    goal_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    result = today_svc.complete_today(db, user, goal, task_id)
    db.commit()
    return result


@router.post("/{goal_id}/today-tasks/{task_id}/uncomplete")
def uncomplete_task(
    goal_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    result = today_svc.uncomplete_today(db, user, goal, task_id)
    db.commit()
    return result


@router.post("/{goal_id}/today-tasks/{task_id}/incomplete")
def incomplete_task(
    goal_id: int,
    task_id: int,
    body: IncompleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    result = today_svc.incomplete_today(db, user, goal, task_id, body.incomplete_reason)
    db.commit()
    return result


@router.post("/{goal_id}/deadline-change")
def deadline_change(
    goal_id: int,
    body: DeadlineChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    today = user_today(user.timezone)
    if body.new_plan_end_date <= goal.plan_end_date:
        raise AppError("DEADLINE_NOT_LATER", "新完成日必须严格晚于当前完成日", 422)
    if body.new_plan_end_date < today + timedelta(days=3):
        raise AppError("DEADLINE_TOO_SOON", "新完成日须 ≥ 今天+3天", 422)
    change = DeadlineChange(
        goal_id=goal.id,
        user_id=user.id,
        old_end_date=goal.plan_end_date,
        new_end_date=body.new_plan_end_date,
        status="pending",
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return {
        "change_id": change.id,
        "status": change.status,
        "current_plan_end_date": goal.plan_end_date.isoformat(),
        "new_plan_end_date": body.new_plan_end_date.isoformat(),
        "earliest_allowed_date": earliest_plan_end(goal.plan_end_date, today).isoformat(),
    }


@router.post("/{goal_id}/deadline-change/{change_id}/confirm")
def deadline_confirm(
    goal_id: int,
    change_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goal = goals_svc.get_owned_goal(db, goal_id, user.id)
    change = db.scalar(
        select(DeadlineChange).where(
            DeadlineChange.id == change_id,
            DeadlineChange.goal_id == goal.id,
            DeadlineChange.user_id == user.id,
        )
    )
    if not change or change.status != "pending":
        raise AppError("NOT_FOUND", "变更记录不存在或不可确认", 404)
    change.status = "confirmed"
    change.confirmed_at = datetime.utcnow()
    db.flush()
    job = enqueue_job(
        db,
        job_type="deadline_replan",
        user_id=user.id,
        goal_id=goal.id,
        deadline_change_id=change.id,
    )
    db.commit()
    response.status_code = 202
    return {
        "change_id": change.id,
        "job_id": job.id,
        "status": "queued",
        "plan_end_date": goal.plan_end_date.isoformat(),
        "pending_new_plan_end_date": change.new_end_date.isoformat(),
    }


@router.post("/{goal_id}/deadline-change/{change_id}/cancel")
def deadline_cancel(
    goal_id: int,
    change_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    goals_svc.get_owned_goal(db, goal_id, user.id)
    change = db.scalar(
        select(DeadlineChange).where(
            DeadlineChange.id == change_id,
            DeadlineChange.goal_id == goal_id,
            DeadlineChange.user_id == user.id,
        )
    )
    if not change:
        raise AppError("NOT_FOUND", "变更记录不存在", 404)
    if change.status not in ("pending", "confirmed", "failed"):
        raise AppError("NOT_FOUND", "变更记录不可取消", 404)
    change.status = "cancelled"
    db.commit()
    return {"change_id": change.id, "status": "cancelled"}
