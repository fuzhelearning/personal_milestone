from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.assignments import (
    delete_generation_assignments,
    migrate_day_entries_for_generation_swap,
)
from app.llm.replan_persist import generation_confirmable
from app.models import DayAssignment, DeadlineChange, Goal, LlmCallLog, TaskNode, User, WbsGeneration
from app.timeutil import user_today


def _node_dict(n: TaskNode) -> dict:
    return {
        "id": n.id,
        "code": n.code,
        "title": n.title,
        "kind": n.kind,
        "parent_id": n.parent_id,
        "progress_pct": n.progress_pct,
        "start_date": n.start_date.isoformat() if n.start_date else None,
        "end_date": n.end_date.isoformat() if n.end_date else None,
        "sort_order": n.sort_order,
    }


def _replan_meta_from_raw(raw: dict) -> dict:
    return {
        k: raw[k]
        for k in (
            "requested_plan_end_date",
            "suggested_plan_end_date",
            "current_plan_end_date",
            "deadline_adjustment",
            "confirmable",
            "suggested_deadline_change",
        )
        if k in raw and raw[k] is not None
    }


def get_generation(db: Session, goal: Goal, generation_id: int) -> WbsGeneration:
    gen = db.scalar(
        select(WbsGeneration).where(
            WbsGeneration.id == generation_id,
            WbsGeneration.goal_id == goal.id,
            WbsGeneration.user_id == goal.user_id,
        )
    )
    if not gen:
        raise AppError("NOT_FOUND", "生成记录不存在", 404)
    return gen


def generation_payload(db: Session, gen: WbsGeneration) -> dict:
    nodes = list(
        db.scalars(
            select(TaskNode)
            .where(TaskNode.generation_id == gen.id)
            .order_by(TaskNode.kind.desc(), TaskNode.sort_order, TaskNode.id)
        ).all()
    )
    nodes.sort(key=lambda n: (0 if n.kind == "milestone" else 1, n.sort_order, n.id))
    tasks = {n.id: n for n in nodes if n.kind == "task"}
    if tasks:
        assigns = db.scalars(
            select(DayAssignment)
            .where(DayAssignment.goal_id == gen.goal_id, DayAssignment.task_id.in_(list(tasks.keys())))
            .order_by(DayAssignment.plan_date, DayAssignment.sort_order)
        ).all()
    else:
        assigns = []

    by_date: dict = defaultdict(list)
    for a in assigns:
        t = tasks.get(a.task_id)
        if not t:
            continue
        by_date[a.plan_date.isoformat()].append({"task_code": t.code, "title": t.title})

    preview = [{"date": d, "items": items} for d, items in sorted(by_date.items())]
    out = {
        "generation_id": gen.id,
        "status": gen.status,
        "version": gen.version,
        "source": gen.source,
        "confirmable": generation_confirmable(gen),
        "structure": {"nodes": [_node_dict(n) for n in nodes]},
        "day_assignments_preview": preview,
    }
    if gen.raw_response:
        try:
            raw = json.loads(gen.raw_response)
            out.update(_replan_meta_from_raw(raw))
            if raw.get("assumptions"):
                out["assumptions"] = raw["assumptions"]
            if raw.get("risks"):
                out["risks"] = raw["risks"]
        except (json.JSONDecodeError, TypeError):
            pass
    return out


def confirm_generation(db: Session, user: User, goal: Goal, gen: WbsGeneration) -> dict:
    if gen.status != "suggested":
        raise AppError("VALIDATION_ERROR", "仅 suggested 状态可确认", 422)
    if gen.source == "deadline_replan" and not generation_confirmable(gen):
        msg = "该重排草案不可确认"
        if gen.raw_response:
            try:
                raw = json.loads(gen.raw_response)
                if raw.get("suggested_deadline_change"):
                    msg = str(raw["suggested_deadline_change"])
            except json.JSONDecodeError:
                pass
        raise AppError("DEADLINE_INSUFFICIENT", msg, 422)
    if gen.raw_response and gen.source != "deadline_replan":
        try:
            raw = json.loads(gen.raw_response)
            if raw.get("suggested_deadline_change"):
                raise AppError(
                    "DEADLINE_INSUFFICIENT",
                    str(raw["suggested_deadline_change"]),
                    422,
                )
        except json.JSONDecodeError:
            pass

    replan_raw: dict | None = None
    if gen.source == "deadline_replan" and gen.raw_response:
        try:
            replan_raw = json.loads(gen.raw_response)
        except json.JSONDecodeError:
            replan_raw = None

    if goal.active_wbs_generation_id:
        old = db.get(WbsGeneration, goal.active_wbs_generation_id)
        if old and old.status == "active":
            migrate_day_entries_for_generation_swap(
                db,
                goal_id=goal.id,
                old_generation_id=old.id,
                new_generation_id=gen.id,
            )
            delete_generation_assignments(db, goal_id=goal.id, generation_id=old.id)
            old.status = "superseded"
            _purge_shorter_tail_assignments(db, goal, user, replan_raw)

    if gen.source == "deadline_replan":
        _apply_pending_deadline(db, goal, gen, replan_raw or {})

    gen.status = "active"
    gen.confirmed_at = datetime.utcnow()
    goal.active_wbs_generation_id = gen.id
    today = user_today(user.timezone)
    goal.status = "planning" if today < goal.plan_start_date else "active"
    goal.updated_at = datetime.utcnow()
    db.flush()
    return {"goal_id": goal.id, "generation_id": gen.id, "status": goal.status}


def _purge_shorter_tail_assignments(
    db: Session,
    goal: Goal,
    user: User,
    replan_raw: dict | None,
) -> None:
    """确认 shorter 草案后清除 (suggested+1)…requested 区间内的 future 安排。"""
    if not replan_raw or replan_raw.get("deadline_adjustment") != "shorter":
        return
    suggested_s = replan_raw.get("suggested_plan_end_date")
    requested_s = replan_raw.get("requested_plan_end_date")
    if not suggested_s or not requested_s:
        return
    suggested = date.fromisoformat(suggested_s)
    requested = date.fromisoformat(requested_s)
    tail_start = suggested + timedelta(days=1)
    if tail_start > requested:
        return
    today = user_today(user.timezone)
    db.execute(
        delete(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.plan_date >= tail_start,
            DayAssignment.plan_date <= requested,
            DayAssignment.plan_date > today,
        )
    )


def cancel_generation(db: Session, goal: Goal, gen: WbsGeneration) -> dict:
    if gen.status != "suggested":
        raise AppError("VALIDATION_ERROR", "仅 suggested 草案可取消", 422)
    if gen.source != "deadline_replan":
        raise AppError("VALIDATION_ERROR", "仅 deadline_replan 草案可取消", 422)
    delete_generation_assignments(db, goal_id=goal.id, generation_id=gen.id)
    gen.status = "cancelled"
    db.flush()
    return {"generation_id": gen.id, "status": gen.status}


def _apply_pending_deadline(
    db: Session,
    goal: Goal,
    gen: WbsGeneration,
    replan_raw: dict,
) -> None:
    """deadline_replan 确认时按 adjustment 写入完成日。"""
    adjustment = replan_raw.get("deadline_adjustment", "none")
    requested_s = replan_raw.get("requested_plan_end_date")
    suggested_s = replan_raw.get("suggested_plan_end_date")

    if adjustment == "shorter" and suggested_s:
        applied = date.fromisoformat(suggested_s)
    elif requested_s:
        applied = date.fromisoformat(requested_s)
    else:
        applied = None

    change: DeadlineChange | None = None
    if gen.llm_call_id:
        log = db.get(LlmCallLog, gen.llm_call_id)
        meta = (log.request_meta or {}) if log else {}
        change_id = meta.get("deadline_change_id")
        if change_id:
            change = db.get(DeadlineChange, change_id)
    if not change:
        change = db.scalar(
            select(DeadlineChange)
            .where(
                DeadlineChange.goal_id == goal.id,
                DeadlineChange.status == "confirmed",
            )
            .order_by(DeadlineChange.confirmed_at.desc())
        )
    if change and change.status == "confirmed" and applied:
        goal.plan_end_date = applied
        change.status = "applied"
        change.applied_end_date = applied
        change.confirmed_at = change.confirmed_at or datetime.utcnow()


def structure_payload(db: Session, goal: Goal) -> dict:
    if not goal.active_wbs_generation_id:
        return {"overall_progress_pct": goal.overall_progress_pct, "nodes": []}
    nodes = list(
        db.scalars(
            select(TaskNode)
            .where(TaskNode.generation_id == goal.active_wbs_generation_id)
            .order_by(TaskNode.sort_order, TaskNode.id)
        ).all()
    )
    nodes.sort(key=lambda n: (0 if n.kind == "milestone" else 1, n.sort_order, n.id))
    return {
        "overall_progress_pct": goal.overall_progress_pct,
        "nodes": [_node_dict(n) for n in nodes],
    }
