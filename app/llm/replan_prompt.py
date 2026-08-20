"""LLM 重排 prompt。"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Goal

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    text = path.read_text(encoding="utf-8")
    # 跳过 markdown 标题行
    lines = text.splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _system_for(job_type: str) -> str:
    if job_type == "sunday_replan":
        return _load_prompt("sunday_replan.v1.md")
    return _load_prompt("deadline_replan.v1.md")


REPLAN_SYSTEM_PROMPT = _system_for("deadline_replan")


def replan_system_prompt(job_type: str) -> str:
    return _system_for(job_type)


def build_replan_user_prompt(goal: Goal, context: dict, *, job_type: str) -> str:
    if job_type == "sunday_replan":
        return (
            f"时区今天：{context['today']}\n"
            f"目标：{json.dumps(context['goal_json'], ensure_ascii=False)}\n"
            f"当前 active 计划（含 day_close_defer/defer 顺延）："
            f"{json.dumps(context['active_plan_json'], ensure_ascii=False)}\n"
            f"未完成任务（id/title/status/remaining）：\n"
            f"{json.dumps(context['open_tasks_json'], ensure_ascii=False, indent=2)}\n"
            f"本周已完成摘要：\n"
            f"{json.dumps(context['done_summary_json'], ensure_ascii=False, indent=2)}\n"
            f"当前未来 day_assignments：\n"
            f"{json.dumps(context['future_assignments_json'], ensure_ascii=False, indent=2)}\n"
            f"跨目标每日负载（明天至 plan_end_date，只读）：\n"
            f"{json.dumps(context['cross_goal_daily_load_json'], ensure_ascii=False, indent=2)}\n\n"
            "请输出调整后的 day_assignments（覆盖需要重排的日期，仅当前目标）。"
            "只输出 JSON，不要解释。"
        )

    return (
        f"时区今天：{context['today']}\n"
        f"目标：{json.dumps(context['goal_json'], ensure_ascii=False)}\n"
        f"当前 active 计划（含 day_close_defer/defer 顺延）："
        f"{json.dumps(context['active_plan_json'], ensure_ascii=False)}\n"
        f"任务完成状态（id/title/status/remaining）：\n"
        f"{json.dumps(context['task_status_json'], ensure_ascii=False, indent=2)}\n"
        f"当前生效完成日：{context['current_plan_end_date']}\n"
        f"用户请求完成日（上限）：{context['new_plan_end_date']}\n"
        f"跨目标每日负载（明天至请求完成日，只读）：\n"
        f"{json.dumps(context['cross_goal_daily_load_json'], ensure_ascii=False, indent=2)}\n\n"
        f"请重排从 {context['tomorrow']} 起至你判定的 suggested_plan_end_date。"
        f"day_assignments 必须完整覆盖到 suggested_plan_end_date（共 {context['replan_day_count']} 天为上限参考），"
        "若 suggested 早于用户请求完成日则 shorter 合法。"
        "只输出 JSON，不要解释。"
    )


def build_replan_retry_suffix(error_zh: str) -> str:
    return (
        "\n\n上次输出不合格，请按错误修正后重新只输出 JSON，不要解释。\n"
        f"错误说明：{error_zh}"
    )
