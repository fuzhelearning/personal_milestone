"""LLM 重排编排：mock 或 DeepSeek；deadline → suggested，sunday → active。"""

from __future__ import annotations

import hashlib
import json

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.llm.deepseek import DeepSeekCallError, chat_completions
from app.llm.generate import _parse_json_text
from app.llm.mock import build_mock_replan
from app.llm.persist import write_llm_call_log
from app.llm.replan_context import build_replan_context
from app.llm.replan_deadline import enrich_replan_response
from app.llm.replan_persist import (
    persist_active_replan,
    persist_suggested_replan,
    supersede_suggested_replan_generations,
)
from app.llm.replan_prompt import (
    build_replan_retry_suffix,
    build_replan_user_prompt,
    replan_system_prompt,
)
from app.llm.replan_validate import validate_replan_payload
from app.llm.validate import WbsValidationError
from app.models import DeadlineChange, Goal, User, WbsGeneration


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _next_version(db: Session, goal_id: int) -> int:
    ver = db.scalar(
        select(func.coalesce(func.max(WbsGeneration.version), 0)).where(
            WbsGeneration.goal_id == goal_id
        )
    )
    return int(ver) + 1


def _validation_sets(context: dict) -> tuple[set[str], set[str], set[str], dict[str, str]]:
    target = context["target_goal"]
    incomplete = set(target["incomplete_tasks"])
    completed = set(target["completed_tasks"])
    milestone_codes = {m["code"] for m in target["milestones"]}
    task_milestone = {
        t["code"]: t["milestone_code"]
        for t in target["tasks"]
        if t.get("milestone_code")
    }
    return incomplete, completed, milestone_codes, task_milestone


def _validate_and_enrich(
    parsed: object,
    *,
    today: date,
    requested: date,
    current: date,
    incomplete: set[str],
    completed: set[str],
    milestone_codes: set[str],
    task_milestone: dict[str, str],
    deadline_replan: bool,
) -> dict:
    payload, meta = validate_replan_payload(
        parsed,
        today=today,
        requested_plan_end_date=requested,
        current_plan_end_date=current,
        incomplete_codes=incomplete,
        completed_codes=completed,
        milestone_codes=milestone_codes,
        task_milestone=task_milestone,
        deadline_replan=deadline_replan,
    )
    if deadline_replan and meta:
        return enrich_replan_response(payload, meta)
    return payload.model_dump(exclude_none=True)


def run_llm_replan(
    db: Session,
    goal: Goal,
    user: User,
    today: date,
    *,
    job_type: str,
    new_plan_end_date: date | None = None,
    deadline_change_id: int | None = None,
) -> WbsGeneration | dict:
    """执行 LLM 重排。deadline_replan 返回 suggested generation；sunday_replan 返回 apply 结果 dict。"""
    if not goal.active_wbs_generation_id:
        raise AppError("VALIDATION_ERROR", "目标尚无 active 计划，无法重排", 422)

    requested = new_plan_end_date or goal.plan_end_date
    current = goal.plan_end_date
    context = build_replan_context(
        db, goal, user, today, requested, trigger=job_type
    )
    incomplete, completed, milestone_codes, task_milestone = _validation_sets(context)

    if not incomplete and not context["target_goal"]["future_assignments"]:
        raise AppError("VALIDATION_ERROR", "无未完成任务需重排", 422)

    settings = get_settings()
    mode = (settings.llm_mode or "").strip().lower()
    is_deadline = job_type == "deadline_replan"
    request_meta = {
        "job_type": job_type,
        "requested_plan_end_date": requested.isoformat(),
        "current_plan_end_date": current.isoformat(),
        "deadline_change_id": deadline_change_id,
    }

    if mode == "mock":
        raw = build_mock_replan(context, goal, today, requested, job_type)
        data = _validate_and_enrich(
            raw,
            today=today,
            requested=requested,
            current=current,
            incomplete=incomplete,
            completed=completed,
            milestone_codes=milestone_codes,
            task_milestone=task_milestone,
            deadline_replan=is_deadline,
        )
        return _persist_replan(
            db,
            goal,
            data,
            today=today,
            job_type=job_type,
            model="mock",
            prompt_hash="mock-replan",
            request_meta=request_meta,
        )

    if mode != "deepseek":
        raise RuntimeError(f"不支持的 llm_mode: {settings.llm_mode!r}")

    system_prompt = replan_system_prompt(job_type)
    user_prompt = build_replan_user_prompt(goal, context, job_type=job_type)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    model = settings.resolved_llm_model()
    ph = _prompt_hash(system_prompt + "\n" + user_prompt)
    last_raw = ""
    last_error = "重排失败"

    for attempt in range(2):
        try:
            raw = chat_completions(messages, max_tokens=8192)
            last_raw = raw or ""
            parsed = _parse_json_text(last_raw)
            data = _validate_and_enrich(
                parsed,
                today=today,
                requested=requested,
                current=current,
                incomplete=incomplete,
                completed=completed,
                milestone_codes=milestone_codes,
                task_milestone=task_milestone,
                deadline_replan=is_deadline,
            )
            return _persist_replan(
                db,
                goal,
                data,
                today=today,
                job_type=job_type,
                model=model,
                prompt_hash=ph,
                request_meta={**request_meta, "attempt": attempt + 1},
            )
        except DeepSeekCallError as exc:
            last_error = str(exc)
            write_llm_call_log(
                db,
                goal,
                purpose=job_type,
                model=model,
                prompt_hash=ph,
                request_meta={**request_meta, "attempt": attempt + 1},
                response_meta={"mode": "deepseek", "attempt": attempt + 1},
                status="failed",
                error_message=last_error,
            )
            if attempt == 0:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt + build_replan_retry_suffix(last_error),
                    },
                ]
            continue
        except WbsValidationError as exc:
            last_error = str(exc)
            write_llm_call_log(
                db,
                goal,
                purpose=job_type,
                model=model,
                prompt_hash=ph,
                request_meta={**request_meta, "attempt": attempt + 1},
                response_meta={
                    "mode": "deepseek",
                    "attempt": attempt + 1,
                    "raw_preview": (last_raw or "")[:2000],
                },
                status="failed",
                error_message=last_error,
            )
            if attempt == 0:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt + build_replan_retry_suffix(last_error),
                    },
                ]
            continue

    if deadline_change_id:
        change = db.get(DeadlineChange, deadline_change_id)
        if change and change.status == "confirmed":
            change.status = "failed"
            db.flush()

    raise AppError("LLM_FAILED", last_error or "重排失败", 502)


def _persist_replan(
    db: Session,
    goal: Goal,
    data: dict,
    *,
    today: date,
    job_type: str,
    model: str,
    prompt_hash: str,
    request_meta: dict,
) -> WbsGeneration | dict:
    log = write_llm_call_log(
        db,
        goal,
        purpose=job_type,
        model=model,
        prompt_hash=prompt_hash,
        request_meta=request_meta,
        response_meta={"mode": model, "job_type": job_type},
        status="succeeded",
    )

    if job_type == "sunday_replan":
        from app.llm.schema import ReplanPayload

        payload = ReplanPayload.model_validate(
            {k: v for k, v in data.items() if k in ReplanPayload.model_fields}
        )
        result = persist_active_replan(
            db,
            goal,
            payload,
            today=today,
            source="sunday_replan",
        )
        result["llm_call_id"] = log.id
        return result

    supersede_suggested_replan_generations(db, goal.id)
    gen = WbsGeneration(
        goal_id=goal.id,
        user_id=goal.user_id,
        version=_next_version(db, goal.id),
        status="suggested",
        source="deadline_replan",
        llm_call_id=log.id,
        raw_response=json.dumps(data, ensure_ascii=False),
    )
    db.add(gen)
    db.flush()
    persist_suggested_replan(
        db,
        goal,
        gen,
        data,
        today=today,
        source="deadline_replan",
    )
    return gen
