"""校验与失败落库单测。"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from sqlalchemy import func, select

from app.llm.generate import run_wbs_generate
from app.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from app.llm.validate import WbsValidationError, validate_wbs_payload
from app.models import DayAssignment, TaskNode, WbsGeneration
from tests.conftest import make_goal


def _valid_plan(start: date, end: date) -> dict:
    days = []
    cur = start
    while cur <= end:
        days.append({"date": cur.isoformat(), "task_codes": ["1.1"]})
        cur = date.fromordinal(cur.toordinal() + 1)
    return {
        "milestones": [
            {
                "code": "1.0",
                "title": "执行",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "tasks": [
                    {
                        "code": "1.1",
                        "title": "推进",
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    }
                ],
            }
        ],
        "day_assignments": days,
    }


def test_prompt_requires_task_objects(db, user):
    goal = make_goal(db, user, start=date(2026, 8, 1), end=date(2026, 8, 3))
    prompt = build_user_prompt(goal)
    assert "共 3 天" in prompt
    assert "对象数组" in SYSTEM_PROMPT or "对象数组" in prompt
    assert '"code": "1.1"' in SYSTEM_PROMPT


def test_reject_two_tasks_same_day(db, user):
    goal = make_goal(db, user, start=date(2026, 8, 1), end=date(2026, 8, 1))
    raw = _valid_plan(goal.plan_start_date, goal.plan_end_date)
    raw["day_assignments"][0]["task_codes"] = ["1.1", "1.2"]
    try:
        validate_wbs_payload(raw, goal)
        raise AssertionError("expected WbsValidationError")
    except WbsValidationError as exc:
        assert "一件" in str(exc) or "task_codes" in str(exc)


def test_reject_missing_day(db, user):
    goal = make_goal(db, user, start=date(2026, 8, 1), end=date(2026, 8, 3))
    raw = _valid_plan(goal.plan_start_date, goal.plan_end_date)
    raw["day_assignments"] = raw["day_assignments"][:2]  # 缺一天
    try:
        validate_wbs_payload(raw, goal)
        raise AssertionError("expected WbsValidationError")
    except WbsValidationError as exc:
        assert "缺少" in str(exc) or "覆盖" in str(exc)


def test_two_failures_write_failed_generation_without_nodes(db, user):
    goal = make_goal(db, user, start=date(2026, 8, 1), end=date(2026, 8, 2))
    bad = '{"milestones": [], "day_assignments": []}'

    class FakeSettings:
        llm_mode = "deepseek"

        def resolved_llm_model(self):
            return "deepseek-chat"

        def resolved_llm_base_url(self):
            return "https://api.deepseek.com"

    with (
        patch("app.llm.generate.get_settings", return_value=FakeSettings()),
        patch("app.llm.generate.chat_completions", return_value=bad) as chat,
    ):
        gen = run_wbs_generate(db, goal)

    assert chat.call_count == 2
    assert gen.status == "failed"
    assert gen.raw_response == bad
    nodes = db.scalar(
        select(func.count()).select_from(TaskNode).where(TaskNode.generation_id == gen.id)
    )
    assigns = db.scalar(
        select(func.count()).select_from(DayAssignment).where(DayAssignment.goal_id == goal.id)
    )
    assert nodes == 0
    assert assigns == 0
    failed_gens = db.scalars(select(WbsGeneration).where(WbsGeneration.goal_id == goal.id)).all()
    assert len(failed_gens) == 1
    assert failed_gens[0].status == "failed"
