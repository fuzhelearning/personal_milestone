"""deadline_replan 双日期语义：requested / suggested / adjustment。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.llm.schema import ReplanPayload
from app.llm.validate import WbsValidationError, _parse_date


@dataclass(frozen=True)
class ReplanDeadlineMeta:
    requested_plan_end_date: date
    current_plan_end_date: date
    suggested_plan_end_date: date
    effective_end: date
    deadline_adjustment: str  # none | shorter | longer
    confirmable: bool


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _max_assignment_date(payload: ReplanPayload) -> date | None:
    if not payload.day_assignments:
        return None
    return max(_parse_date(row.date, "day_assignments.date") for row in payload.day_assignments)


def resolve_suggested_plan_end_date(payload: ReplanPayload) -> date | None:
    if payload.suggested_plan_end_date:
        return _parse_date(payload.suggested_plan_end_date, "suggested_plan_end_date")
    return _max_assignment_date(payload)


def compute_replan_deadline_meta(
    payload: ReplanPayload,
    *,
    requested_plan_end_date: date,
    current_plan_end_date: date,
) -> ReplanDeadlineMeta:
    explicit = (
        _parse_date(payload.suggested_plan_end_date, "suggested_plan_end_date")
        if payload.suggested_plan_end_date
        else None
    )
    inferred_max = _max_assignment_date(payload)

    if payload.suggested_deadline_change and not explicit and inferred_max is None:
        implied = requested_plan_end_date + timedelta(days=1)
        return ReplanDeadlineMeta(
            requested_plan_end_date=requested_plan_end_date,
            current_plan_end_date=current_plan_end_date,
            suggested_plan_end_date=implied,
            effective_end=implied,
            deadline_adjustment="longer",
            confirmable=False,
        )

    suggested = explicit or inferred_max or requested_plan_end_date

    if suggested <= current_plan_end_date:
        raise WbsValidationError(
            f"suggested_plan_end_date 必须严格晚于当前生效完成日 "
            f"({current_plan_end_date.isoformat()})"
        )

    if suggested > requested_plan_end_date:
        adjustment = "longer"
        confirmable = False
        effective_end = suggested
    elif suggested < requested_plan_end_date:
        adjustment = "shorter"
        confirmable = True
        effective_end = suggested
    else:
        adjustment = "none"
        confirmable = True
        effective_end = requested_plan_end_date

    if adjustment == "longer" and payload.suggested_deadline_change:
        confirmable = False

    return ReplanDeadlineMeta(
        requested_plan_end_date=requested_plan_end_date,
        current_plan_end_date=current_plan_end_date,
        suggested_plan_end_date=suggested,
        effective_end=effective_end,
        deadline_adjustment=adjustment,
        confirmable=confirmable,
    )


def enrich_replan_response(
    payload: ReplanPayload,
    meta: ReplanDeadlineMeta,
) -> dict:
    data = payload.model_dump(exclude_none=True)
    data["requested_plan_end_date"] = meta.requested_plan_end_date.isoformat()
    data["current_plan_end_date"] = meta.current_plan_end_date.isoformat()
    data["suggested_plan_end_date"] = meta.suggested_plan_end_date.isoformat()
    data["deadline_adjustment"] = meta.deadline_adjustment
    data["confirmable"] = meta.confirmable
    return data
