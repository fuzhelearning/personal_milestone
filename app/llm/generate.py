"""wbs_generate 编排：mock 假数据或 DeepSeek（最多 2 次），共用落库。"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm.deepseek import DeepSeekCallError, chat_completions
from app.llm.mock import build_mock_plan
from app.llm.persist import persist_failed_generation, persist_succeeded_generation, write_llm_call_log
from app.llm.prompt import (
    SYSTEM_PROMPT,
    build_retry_user_suffix,
    build_user_prompt,
    goal_request_meta,
)
from app.llm.validate import WbsValidationError, validate_wbs_payload
from app.models import Goal, WbsGeneration


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _parse_json_text(raw: str) -> object:
    text = (raw or "").strip()
    if text.startswith("```"):
        # 偶发围栏：尽量剥掉再解析；仍失败则交给校验错误
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError as exc:
            raise WbsValidationError(f"非合法 JSON: {exc.msg}") from exc


def run_wbs_generate(db: Session, goal: Goal) -> WbsGeneration:
    """按 llm_mode 生成并落库。返回 suggested 或 failed 的 WbsGeneration。"""
    settings = get_settings()
    mode = (settings.llm_mode or "").strip().lower()
    request_meta = goal_request_meta(goal)

    if mode == "mock":
        raw_plan = build_mock_plan(goal)
        # 去掉非 schema 字段后再校验
        clean = {k: v for k, v in raw_plan.items() if k in ("milestones", "day_assignments", "assumptions", "risks", "suggested_deadline_change")}
        payload = validate_wbs_payload(clean, goal)
        return persist_succeeded_generation(
            db,
            goal,
            payload,
            model="mock",
            prompt_hash="mock",
            request_meta=request_meta,
            response_meta={"mode": "mock"},
        )

    if mode != "deepseek":
        raise RuntimeError(f"不支持的 llm_mode: {settings.llm_mode!r}")

    user_prompt = build_user_prompt(goal)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    model = settings.resolved_llm_model()
    ph = _prompt_hash(SYSTEM_PROMPT + "\n" + user_prompt)
    last_raw = ""
    last_error = "生成失败"
    last_log_id: int | None = None

    for attempt in range(2):
        try:
            raw = chat_completions(messages)
            last_raw = raw or ""
            parsed = _parse_json_text(last_raw)
            payload = validate_wbs_payload(parsed, goal)
            return persist_succeeded_generation(
                db,
                goal,
                payload,
                model=model,
                prompt_hash=ph,
                request_meta={**request_meta, "attempt": attempt + 1},
                response_meta={"mode": "deepseek", "attempt": attempt + 1},
            )
        except DeepSeekCallError as exc:
            last_raw = exc.raw_response or last_raw
            last_error = str(exc)
            log = write_llm_call_log(
                db,
                goal,
                model=model,
                prompt_hash=ph,
                request_meta={**request_meta, "attempt": attempt + 1},
                response_meta={"mode": "deepseek", "attempt": attempt + 1},
                status="failed",
                error_message=last_error,
            )
            last_log_id = log.id
            if attempt == 0:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_prompt + build_retry_user_suffix(last_error),
                    },
                ]
            continue
        except WbsValidationError as exc:
            last_error = str(exc)
            log = write_llm_call_log(
                db,
                goal,
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
            last_log_id = log.id
            if attempt == 0:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_prompt + build_retry_user_suffix(last_error),
                    },
                ]
            continue

    return persist_failed_generation(
        db,
        goal,
        raw_response=last_raw,
        error_message=last_error,
        llm_call_id=last_log_id,
    )
