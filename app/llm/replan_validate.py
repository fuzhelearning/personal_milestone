"""重排 delta 校验。"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import ValidationError

from app.llm.replan_deadline import ReplanDeadlineMeta, compute_replan_deadline_meta
from app.llm.schema import ReplanPayload
from app.llm.validate import WbsValidationError, _parse_date, _reject_forbidden_fields


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def validate_replan_payload(
    raw: object,
    *,
    today: date,
    requested_plan_end_date: date,
    current_plan_end_date: date | None = None,
    incomplete_codes: set[str],
    completed_codes: set[str],
    milestone_codes: set[str],
    task_milestone: dict[str, str],
    deadline_replan: bool = False,
) -> tuple[ReplanPayload, ReplanDeadlineMeta | None]:
    """校验 LLM 重排输出。deadline_replan 时返回双日期 meta。"""
    if not isinstance(raw, dict):
        raise WbsValidationError("输出必须是 JSON 对象")
    _reject_forbidden_fields(raw)

    try:
        payload = ReplanPayload.model_validate(raw)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", "校验失败")
            msgs.append(f"{loc}: {msg}" if loc else msg)
        raise WbsValidationError("；".join(msgs) or "JSON 形状不合格") from exc

    current = current_plan_end_date or requested_plan_end_date
    meta: ReplanDeadlineMeta | None = None
    if deadline_replan:
        meta = compute_replan_deadline_meta(
            payload,
            requested_plan_end_date=requested_plan_end_date,
            current_plan_end_date=current,
        )
        if meta.deadline_adjustment == "longer":
            return payload, meta

    cap_end = meta.effective_end if meta else requested_plan_end_date
    tomorrow = today + timedelta(days=1)
    if tomorrow > cap_end and not (meta and meta.deadline_adjustment == "longer"):
        raise WbsValidationError("新计划结束日早于明天，无法重排未来安排")

    for tu in payload.task_updates:
        if tu.code in completed_codes:
            raise WbsValidationError(f"已完成任务不可更新: {tu.code}")
        if tu.code not in incomplete_codes:
            raise WbsValidationError(f"task_updates 引用未知或未完成任务: {tu.code}")
        t_start = _parse_date(tu.start_date, f"任务 {tu.code} start_date")
        t_end = _parse_date(tu.end_date, f"任务 {tu.code} end_date")
        if t_end < t_start:
            raise WbsValidationError(f"任务 {tu.code} 结束早于开始")
        if t_end > cap_end:
            raise WbsValidationError(f"任务 {tu.code} end_date 超出有效计划结束日")
        if meta and t_end > meta.suggested_plan_end_date:
            raise WbsValidationError(
                f"任务 {tu.code} end_date 超出 suggested_plan_end_date"
            )

    mil_end: dict[str, date] = {}
    for mu in payload.milestone_updates:
        if mu.code not in milestone_codes:
            raise WbsValidationError(f"milestone_updates 引用未知里程碑: {mu.code}")
        end = _parse_date(mu.end_date, f"里程碑 {mu.code} end_date")
        if end > cap_end:
            raise WbsValidationError(f"里程碑 {mu.code} end_date 超出有效计划结束日")
        if meta and end > meta.suggested_plan_end_date:
            raise WbsValidationError(
                f"里程碑 {mu.code} end_date 超出 suggested_plan_end_date"
            )
        mil_end[mu.code] = end

    for tu in payload.task_updates:
        mc = task_milestone.get(tu.code)
        if mc and mc in mil_end:
            t_end = _parse_date(tu.end_date, f"任务 {tu.code} end_date")
            if t_end > mil_end[mc]:
                raise WbsValidationError(f"任务 {tu.code} end_date 超出所属里程碑 {mc} 新 end_date")

    seen: set[date] = set()
    for row in payload.day_assignments:
        d = _parse_date(row.date, "day_assignments.date")
        if d in seen:
            raise WbsValidationError(f"日期重复: {d.isoformat()}")
        seen.add(d)
        if d <= today:
            raise WbsValidationError(f"日安排不得覆盖今天及以前: {d.isoformat()}")
        if d > requested_plan_end_date:
            raise WbsValidationError(f"日安排超出用户请求完成日: {d.isoformat()}")
        if meta and meta.deadline_adjustment == "shorter" and d > meta.suggested_plan_end_date:
            raise WbsValidationError(
                f"shorter 场景日安排不得晚于 suggested: {d.isoformat()}"
            )
        if not meta and d > requested_plan_end_date:
            raise WbsValidationError(f"日安排超出新计划结束日: {d.isoformat()}")
        code = row.task_codes[0]
        if code in completed_codes:
            raise WbsValidationError(f"已完成任务不可排入未来: {code}")
        if code not in incomplete_codes:
            raise WbsValidationError(f"day_assignments 引用未知或未完成任务: {code}")

    if meta and meta.deadline_adjustment == "longer":
        return payload, meta

    if meta and meta.deadline_adjustment == "shorter":
        expected = {d for d in _daterange(tomorrow, meta.suggested_plan_end_date)}
    else:
        expected = {d for d in _daterange(tomorrow, requested_plan_end_date)}

    missing = sorted(expected - seen)
    if missing:
        raise WbsValidationError(
            f"day_assignments 未覆盖每一天，缺少: {missing[0].isoformat()}"
            + (f" 等 {len(missing)} 天" if len(missing) > 1 else "")
        )

    if meta and meta.deadline_adjustment == "none":
        extra = sorted(seen - expected)
        if extra:
            raise WbsValidationError(f"day_assignments 含计划外日期: {extra[0].isoformat()}")

    return payload, meta
