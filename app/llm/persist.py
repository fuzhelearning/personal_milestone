"""WBS 生成落库：成功 suggested + 节点/日安排；失败仅 generation + log。"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm.schema import WbsGeneratePayload
from app.models import DayAssignment, Goal, LlmCallLog, TaskNode, WbsGeneration


def _next_version(db: Session, goal_id: int) -> int:
    ver = db.scalar(
        select(func.coalesce(func.max(WbsGeneration.version), 0)).where(WbsGeneration.goal_id == goal_id)
    )
    return int(ver) + 1


def write_llm_call_log(
    db: Session,
    goal: Goal,
    *,
    model: str,
    prompt_hash: str,
    request_meta: dict,
    response_meta: dict | None,
    status: str,
    error_message: str | None = None,
) -> LlmCallLog:
    log = LlmCallLog(
        user_id=goal.user_id,
        goal_id=goal.id,
        purpose="wbs_generate",
        model=model,
        prompt_hash=prompt_hash,
        request_meta=request_meta,
        response_meta=response_meta,
        status=status,
        error_message=error_message,
    )
    db.add(log)
    db.flush()
    return log


def persist_succeeded_generation(
    db: Session,
    goal: Goal,
    payload: WbsGeneratePayload | dict,
    *,
    model: str,
    prompt_hash: str,
    request_meta: dict,
    response_meta: dict | None = None,
) -> WbsGeneration:
    """成功落库：succeeded log + suggested generation + nodes + source=ai assignments。"""
    if isinstance(payload, WbsGeneratePayload):
        data = payload.model_dump(exclude_none=True)
    else:
        data = payload

    log = write_llm_call_log(
        db,
        goal,
        model=model,
        prompt_hash=prompt_hash,
        request_meta=request_meta,
        response_meta=response_meta or {},
        status="succeeded",
    )

    gen = WbsGeneration(
        goal_id=goal.id,
        user_id=goal.user_id,
        version=_next_version(db, goal.id),
        status="suggested",
        source="ai",
        llm_call_id=log.id,
        raw_response=json.dumps(data, ensure_ascii=False),
    )
    db.add(gen)
    db.flush()

    code_to_task_id: dict[str, int] = {}
    sort_m = 0
    for m in data["milestones"]:
        ms = TaskNode(
            generation_id=gen.id,
            goal_id=goal.id,
            user_id=goal.user_id,
            parent_id=None,
            kind="milestone",
            code=m["code"],
            title=m["title"],
            sort_order=sort_m,
            start_date=date.fromisoformat(m["start_date"]),
            end_date=date.fromisoformat(m["end_date"]),
        )
        db.add(ms)
        db.flush()
        sort_m += 1
        sort_t = 0
        for t in m["tasks"]:
            node = TaskNode(
                generation_id=gen.id,
                goal_id=goal.id,
                user_id=goal.user_id,
                parent_id=ms.id,
                kind="task",
                code=t["code"],
                title=t["title"],
                description=t.get("description"),
                sort_order=sort_t,
                start_date=date.fromisoformat(t["start_date"]),
                end_date=date.fromisoformat(t["end_date"]),
            )
            db.add(node)
            db.flush()
            code_to_task_id[t["code"]] = node.id
            sort_t += 1

    for i, row in enumerate(data["day_assignments"]):
        tid = code_to_task_id.get(row["task_codes"][0])
        if not tid:
            continue
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=tid,
                plan_date=date.fromisoformat(row["date"]),
                source="ai",
                sort_order=i,
            )
        )

    return gen


def persist_failed_generation(
    db: Session,
    goal: Goal,
    *,
    raw_response: str,
    error_message: str,
    llm_call_id: int | None = None,
) -> WbsGeneration:
    """失败落库：failed generation（保留原文），不写节点/日安排。尝试 log 由调用方按次写入。"""
    gen = WbsGeneration(
        goal_id=goal.id,
        user_id=goal.user_id,
        version=_next_version(db, goal.id),
        status="failed",
        source="ai",
        llm_call_id=llm_call_id,
        raw_response=raw_response or "",
    )
    db.add(gen)
    db.flush()
    # error_message 仅用于调用方日志上下文；generation 表无该列
    _ = error_message
    return gen
