"""WBS 生成业务不变量校验。"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import ValidationError

from app.llm.schema import WbsGeneratePayload
from app.models import Goal

_FORBIDDEN_KEYS = frozenset(
    {
        "minutes",
        "story_points",
        "storyPoints",
        "estimate_minutes",
        "estimated_minutes",
        "hours",
        "effort",
    }
)


class WbsValidationError(ValueError):
    """中文错误说明，可供第二次请求反馈。"""


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _reject_forbidden_fields(raw: object, path: str = "") -> None:
    if isinstance(raw, dict):
        for key, val in raw.items():
            if key in _FORBIDDEN_KEYS:
                raise WbsValidationError(f"禁止字段 {key}（不得输出分钟/故事点等）")
            _reject_forbidden_fields(val, f"{path}.{key}" if path else key)
    elif isinstance(raw, list):
        for i, item in enumerate(raw):
            _reject_forbidden_fields(item, f"{path}[{i}]")


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WbsValidationError(f"{label} 日期非法: {value}") from exc


def validate_wbs_payload(raw: object, goal: Goal) -> WbsGeneratePayload:
    """硬校验 JSON 形状与业务不变量；失败抛出 WbsValidationError（中文）。"""
    if not isinstance(raw, dict):
        raise WbsValidationError("输出必须是 JSON 对象")
    _reject_forbidden_fields(raw)

    try:
        payload = WbsGeneratePayload.model_validate(raw)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", "校验失败")
            if "task_codes" in loc and (
                "max_length" in msg or "长度" in msg or "at most" in msg.lower() or "too_long" in str(err.get("type", ""))
            ):
                msgs.append(f"{loc}: 每天恰好一件任务，不可安排多件（不得取第一件凑合）")
            else:
                msgs.append(f"{loc}: {msg}" if loc else msg)
        raise WbsValidationError("；".join(msgs) or "JSON 形状不合格") from exc

    plan_start, plan_end = goal.plan_start_date, goal.plan_end_date
    if plan_end < plan_start:
        raise WbsValidationError("目标计划结束早于开始")

    codes: set[str] = set()
    task_by_code: dict[str, tuple[date, date, date, date]] = {}
    # task_code -> (task_start, task_end, mil_start, mil_end)

    for m in payload.milestones:
        if m.code in codes:
            raise WbsValidationError(f"code 重复: {m.code}")
        codes.add(m.code)
        mil_start = _parse_date(m.start_date, f"里程碑 {m.code} start_date")
        mil_end = _parse_date(m.end_date, f"里程碑 {m.code} end_date")
        if mil_end < mil_start:
            raise WbsValidationError(f"里程碑 {m.code} 结束早于开始")
        if mil_start < plan_start or mil_end > plan_end:
            raise WbsValidationError(f"里程碑 {m.code} 日期超出计划窗")

        for t in m.tasks:
            if t.code in codes:
                raise WbsValidationError(f"code 重复: {t.code}")
            codes.add(t.code)
            t_start = _parse_date(t.start_date, f"任务 {t.code} start_date")
            t_end = _parse_date(t.end_date, f"任务 {t.code} end_date")
            if t_end < t_start:
                raise WbsValidationError(f"任务 {t.code} 结束早于开始")
            if t_start < mil_start or t_end > mil_end:
                raise WbsValidationError(f"任务 {t.code} 日期不在所属里程碑窗内")
            if t_start < plan_start or t_end > plan_end:
                raise WbsValidationError(f"任务 {t.code} 日期超出计划窗")
            task_by_code[t.code] = (t_start, t_end, mil_start, mil_end)

    if not task_by_code:
        raise WbsValidationError("至少需要一个任务")

    expected_days = {d for d in _daterange(plan_start, plan_end)}
    seen_days: set[date] = set()
    for row in payload.day_assignments:
        d = _parse_date(row.date, "day_assignments.date")
        if d in seen_days:
            raise WbsValidationError(f"日期重复: {d.isoformat()}")
        seen_days.add(d)
        if d < plan_start or d > plan_end:
            raise WbsValidationError(f"日安排日期超出计划窗: {d.isoformat()}")
        code = row.task_codes[0]
        if code not in task_by_code:
            raise WbsValidationError(f"task_code 未定义: {code}")
        t_start, t_end, _ms, _me = task_by_code[code]
        if d < t_start or d > t_end:
            raise WbsValidationError(f"日安排 {d.isoformat()} 的任务 {code} 不在任务日期窗内")

    missing = sorted(expected_days - seen_days)
    if missing:
        raise WbsValidationError(
            f"day_assignments 未覆盖计划每一天，缺少: {missing[0].isoformat()}"
            + (f" 等 {len(missing)} 天" if len(missing) > 1 else "")
        )
    extra = sorted(seen_days - expected_days)
    if extra:
        raise WbsValidationError(f"day_assignments 含计划外日期: {extra[0].isoformat()}")

    return payload
