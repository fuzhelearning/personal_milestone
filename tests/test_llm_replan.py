"""LLM 重排：mock 模式集成测试。"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import select

from app.llm.replan_context import build_replan_context
from app.llm.replan_run import run_llm_replan
from app.llm.replan_validate import validate_replan_payload
from app.models import DayAssignment, DeadlineChange, WbsGeneration
from app.services.day_close import _close_goal_day
from app.services.jobs import enqueue_job
from app.services.wbs import cancel_generation, confirm_generation
from tests.conftest import make_goal, seed_active_wbs


def _mock_settings():
    from app.config import Settings

    return Settings(
        app_env="dev",
        database_url="sqlite://",
        jwt_secret="test-secret-key-12345",
        jwt_expire_seconds=3600,
        llm_mode="mock",
        llm_api_key="test",
        llm_model="mock",
        llm_base_url="http://mock",
        internal_token="test-internal-token-123",
        wechat_mock=True,
    )


def test_build_replan_context_cross_goal_defer_remaining(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=5)
    goal_a = make_goal(db, user, start=today, end=end, title="目标A")
    goal_b = make_goal(db, user, start=today, end=end, title="目标B")
    tasks_a = seed_active_wbs(db, goal_a, task_count=2)
    tasks_b = seed_active_wbs(db, goal_b, task_count=1)
    goal_a.status = "active"
    goal_b.status = "active"
    db.add(
        DayAssignment(
            goal_id=goal_a.id,
            user_id=user.id,
            task_id=tasks_a[0].id,
            plan_date=today + timedelta(days=1),
            source="day_close_defer",
            sort_order=0,
        )
    )
    db.add(
        DayAssignment(
            goal_id=goal_b.id,
            user_id=user.id,
            task_id=tasks_b[0].id,
            plan_date=today + timedelta(days=1),
            source="ai",
            sort_order=0,
        )
    )
    db.commit()

    ctx = build_replan_context(db, goal_a, user, today, end + timedelta(days=2))
    assert ctx["cross_goal_daily_load_json"]
    assert any(t["remaining_days"] >= 0 for t in ctx["task_status_json"])
    defer_rows = [a for a in ctx["active_plan_json"]["future_assignments"] if a["source"] == "day_close_defer"]
    assert defer_rows


def test_llm_replan_creates_suggested_generation(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=5)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=3)
    db.commit()

    new_end = end + timedelta(days=3)
    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=new_end,
        )

    assert gen.status == "suggested"
    assert gen.source == "deadline_replan"
    future = list(
        db.scalars(
            select(DayAssignment)
            .where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date > today,
            )
            .order_by(DayAssignment.plan_date)
        ).all()
    )
    assert len(future) == (new_end - today).days
    assert goal.plan_end_date == end
    assert goal.active_wbs_generation_id != gen.id


def test_confirm_replan_applies_deadline(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=3)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=2)
    new_end = end + timedelta(days=2)
    change = DeadlineChange(
        goal_id=goal.id,
        user_id=user.id,
        old_end_date=end,
        new_end_date=new_end,
        status="confirmed",
    )
    db.add(change)
    db.flush()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=new_end,
            deadline_change_id=change.id,
        )

    assert goal.plan_end_date == end
    with patch("app.services.wbs.user_today", return_value=today):
        confirm_generation(db, user, goal, gen)

    db.flush()
    db.refresh(goal)
    db.refresh(change)
    assert goal.plan_end_date == new_end
    assert change.status == "applied"
    assert goal.active_wbs_generation_id == gen.id
    active_gen = db.get(WbsGeneration, gen.id)
    assert active_gen.status == "active"


def test_cancel_replan_zero_change(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=4)
    goal = make_goal(db, user, start=today, end=end)
    active_id = seed_active_wbs(db, goal, task_count=2)
    goal.active_wbs_generation_id  # noqa: B018
    db.commit()
    old_active = goal.active_wbs_generation_id
    new_end = end + timedelta(days=2)

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=new_end,
        )

    cancel_generation(db, goal, gen)
    db.flush()
    db.refresh(goal)
    assert goal.plan_end_date == end
    assert goal.active_wbs_generation_id == old_active


def test_suggested_deadline_change_not_confirmable(db, user):
    today = date(2026, 8, 1)
    goal = make_goal(db, user, start=today, end=today)
    seed_active_wbs(db, goal, task_count=3)
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=today,
        )

    import pytest

    from app.errors import AppError

    assert gen.raw_response and "suggested_deadline_change" in gen.raw_response
    with pytest.raises(AppError) as exc:
        confirm_generation(db, user, goal, gen)
    assert exc.value.code == "DEADLINE_INSUFFICIENT"


def test_replan_failure_leaves_active_unchanged(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=5)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=2)
    db.commit()
    old_end = goal.plan_end_date
    old_active = goal.active_wbs_generation_id

    from app.config import Settings
    from app.llm.deepseek import DeepSeekCallError

    deepseek_settings = Settings(
        app_env="dev",
        database_url="sqlite://",
        jwt_secret="test-secret-key-12345",
        jwt_expire_seconds=3600,
        llm_mode="deepseek",
        llm_api_key="test",
        llm_model="deepseek-chat",
        llm_base_url="http://mock",
        internal_token="test-internal-token-123",
        wechat_mock=True,
    )

    import pytest

    from app.errors import AppError

    with patch("app.llm.replan_run.get_settings", return_value=deepseek_settings):
        with patch(
            "app.llm.replan_run.chat_completions",
            side_effect=DeepSeekCallError("api down"),
        ):
            with pytest.raises(AppError):
                run_llm_replan(
                    db,
                    goal,
                    user,
                    today,
                    job_type="deadline_replan",
                    new_plan_end_date=end + timedelta(days=2),
                )

    db.refresh(goal)
    assert goal.plan_end_date == old_end
    assert goal.active_wbs_generation_id == old_active


def test_sunday_replan_writes_active_directly(db, user):
    today = date(2026, 8, 2)  # Sunday
    assert today.weekday() == 6
    end = today + timedelta(days=4)
    goal = make_goal(db, user, start=today - timedelta(days=2), end=end)
    tasks = seed_active_wbs(db, goal, task_count=2)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=user.id,
            task_id=tasks[0].id,
            plan_date=today + timedelta(days=1),
            source="ai",
            sort_order=0,
        )
    )
    db.commit()
    active_gen_id = goal.active_wbs_generation_id

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        result = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="sunday_replan",
            new_plan_end_date=end,
        )

    assert result["applied"] is True
    assert goal.active_wbs_generation_id == active_gen_id
    suggested = list(
        db.scalars(
            select(WbsGeneration).where(
                WbsGeneration.goal_id == goal.id,
                WbsGeneration.status == "suggested",
            )
        ).all()
    )
    assert not suggested


def test_sunday_day_close_updates_active(db, user):
    today = date(2026, 8, 2)  # Sunday
    end = today + timedelta(days=4)
    goal = make_goal(db, user, start=today - timedelta(days=2), end=end)
    seed_active_wbs(db, goal, task_count=2)
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        _close_goal_day(db, user, goal, today)

    future = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date > today,
            )
        ).all()
    )
    assert future
    assert any(a.source == "sunday_replan" for a in future)


def test_enqueue_deadline_replan_links_change(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=5)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=2)
    goal.status = "active"
    new_end = end + timedelta(days=2)
    change = DeadlineChange(
        goal_id=goal.id,
        user_id=user.id,
        old_end_date=end,
        new_end_date=new_end,
        status="confirmed",
    )
    db.add(change)
    db.flush()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        job = enqueue_job(
            db,
            job_type="deadline_replan",
            user_id=user.id,
            goal_id=goal.id,
            deadline_change_id=change.id,
            process_now=True,
        )

    db.refresh(change)
    assert change.job_id == job.id
    assert job.result_ref_json.get("generation_id")
    assert job.result_ref_json.get("deadline_change_id") == change.id
    assert goal.plan_end_date == end


def test_replan_preserves_today_assignment(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=4)
    goal = make_goal(db, user, start=today, end=end)
    tasks = seed_active_wbs(db, goal, task_count=2)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=goal.user_id,
            task_id=tasks[0].id,
            plan_date=today,
            source="ai",
            sort_order=0,
        )
    )
    db.commit()

    new_end = end + timedelta(days=2)
    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=new_end,
        )

    today_rows = list(
        db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date == today,
            )
        ).all()
    )
    assert len(today_rows) >= 1

    from app.models import TaskNode

    new_tasks = list(
        db.scalars(select(TaskNode).where(TaskNode.generation_id == gen.id, TaskNode.kind == "task")).all()
    )
    code_to_id = {t.code: t.id for t in new_tasks}
    today_on_gen = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == code_to_id["1.1"],
            DayAssignment.plan_date == today,
        )
    )
    assert today_on_gen is not None


def _shorter_mock_payload(today: date, suggested: date) -> dict:
    """AC-012：只排到 suggested，requested 尾部无任务。"""
    tomorrow = today + timedelta(days=1)
    days = []
    codes = ["1.1", "1.2", "1.3"]
    cur = tomorrow
    idx = 0
    while cur <= suggested:
        days.append({"date": cur.isoformat(), "task_codes": [codes[idx % 3]]})
        cur += timedelta(days=1)
        idx += 1
    return {
        "task_updates": [
            {"code": c, "start_date": tomorrow.isoformat(), "end_date": suggested.isoformat()}
            for c in codes
        ],
        "milestone_updates": [{"code": "1.0", "end_date": suggested.isoformat()}],
        "day_assignments": days,
        "suggested_plan_end_date": suggested.isoformat(),
        "assumptions": ["test-shorter"],
    }


def test_shorter_replan_succeeds_ac012(db, user):
    today = date(2026, 8, 19)
    end = date(2026, 9, 1)
    requested = date(2026, 9, 30)
    suggested = date(2026, 9, 17)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=3)
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        with patch(
            "app.llm.replan_run.build_mock_replan",
            return_value=_shorter_mock_payload(today, suggested),
        ):
            gen = run_llm_replan(
                db,
                goal,
                user,
                today,
                job_type="deadline_replan",
                new_plan_end_date=requested,
            )

    import json

    data = json.loads(gen.raw_response)
    assert data["deadline_adjustment"] == "shorter"
    assert data["confirmable"] is True
    assert data["requested_plan_end_date"] == requested.isoformat()
    assert data["suggested_plan_end_date"] == suggested.isoformat()
    future_dates = [
        a.plan_date
        for a in db.scalars(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.plan_date > today,
            )
        ).all()
    ]
    assert future_dates
    assert max(future_dates) <= suggested


def test_longer_replan_succeeded_not_confirmable_ac013(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=3)
    requested = end + timedelta(days=2)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=2)
    db.commit()

    longer_raw = {
        "task_updates": [],
        "milestone_updates": [],
        "day_assignments": [],
        "suggested_plan_end_date": (requested + timedelta(days=5)).isoformat(),
        "suggested_deadline_change": "建议延至更晚",
        "assumptions": ["test-longer"],
    }

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        with patch("app.llm.replan_run.build_mock_replan", return_value=longer_raw):
            gen = run_llm_replan(
                db,
                goal,
                user,
                today,
                job_type="deadline_replan",
                new_plan_end_date=requested,
            )

    import json

    data = json.loads(gen.raw_response)
    assert data["deadline_adjustment"] == "longer"
    assert data["confirmable"] is False
    assert goal.plan_end_date == end


def test_none_replan_full_coverage_ac014(db, user):
    today = date(2026, 8, 1)
    end = today + timedelta(days=3)
    requested = end + timedelta(days=2)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=2)
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        gen = run_llm_replan(
            db,
            goal,
            user,
            today,
            job_type="deadline_replan",
            new_plan_end_date=requested,
        )

    import json

    data = json.loads(gen.raw_response)
    assert data["deadline_adjustment"] == "none"
    assert data["confirmable"] is True
    assert data["suggested_plan_end_date"] == requested.isoformat()


def test_shorter_partial_days_not_repaired_ac015(db, user):
    today = date(2026, 8, 19)
    requested = date(2026, 9, 30)
    current = date(2026, 9, 1)
    partial = {
        "task_updates": [
            {"code": "1.1", "start_date": "2026-08-20", "end_date": "2026-09-17"}
        ],
        "milestone_updates": [{"code": "1.0", "end_date": "2026-09-17"}],
        "day_assignments": [
            {"date": "2026-08-20", "task_codes": ["1.1"]},
            {"date": "2026-09-17", "task_codes": ["1.1"]},
        ],
        "suggested_plan_end_date": "2026-09-17",
    }
    import pytest

    from app.llm.validate import WbsValidationError

    with pytest.raises(WbsValidationError, match="未覆盖"):
        validate_replan_payload(
            partial,
            today=today,
            requested_plan_end_date=requested,
            current_plan_end_date=current,
            incomplete_codes={"1.1", "1.2", "1.3"},
            completed_codes=set(),
            milestone_codes={"1.0"},
            task_milestone={"1.1": "1.0", "1.2": "1.0", "1.3": "1.0"},
            deadline_replan=True,
        )


def test_confirm_shorter_writes_suggested_date(db, user):
    today = date(2026, 8, 19)
    end = date(2026, 9, 1)
    requested = date(2026, 9, 30)
    suggested = date(2026, 9, 17)
    goal = make_goal(db, user, start=today, end=end)
    seed_active_wbs(db, goal, task_count=3)
    change = DeadlineChange(
        goal_id=goal.id,
        user_id=user.id,
        old_end_date=end,
        new_end_date=requested,
        status="confirmed",
    )
    db.add(change)
    db.flush()
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        with patch(
            "app.llm.replan_run.build_mock_replan",
            return_value=_shorter_mock_payload(today, suggested),
        ):
            gen = run_llm_replan(
                db,
                goal,
                user,
                today,
                job_type="deadline_replan",
                new_plan_end_date=requested,
                deadline_change_id=change.id,
            )

    with patch("app.services.wbs.user_today", return_value=today):
        confirm_generation(db, user, goal, gen)

    db.refresh(goal)
    db.refresh(change)
    assert goal.plan_end_date == suggested
    assert change.applied_end_date == suggested
    assert change.new_end_date == requested
