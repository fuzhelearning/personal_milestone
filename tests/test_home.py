"""首页只展示 active generation 的日安排。"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from app.models import DayAssignment
from app.services.home import build_home
from app.services.jobs import enqueue_job
from tests.conftest import make_goal, seed_active_wbs
from tests.test_llm_replan import _mock_settings


def test_home_excludes_suggested_replan_assignments(db, user):
    today = date(2026, 8, 19)
    end = today + timedelta(days=5)
    goal = make_goal(db, user, start=today, end=end, title="leetcode hot100")
    tasks = seed_active_wbs(db, goal, task_count=2)
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=user.id,
            task_id=tasks[0].id,
            plan_date=today,
            source="ai",
            sort_order=0,
        )
    )
    db.commit()

    with patch("app.llm.replan_run.get_settings", return_value=_mock_settings()):
        enqueue_job(
            db,
            job_type="deadline_replan",
            user_id=user.id,
            goal_id=goal.id,
        )

    home = build_home(db, user)
    day2_titles = [t["title"] for t in home["today_tasks"] if t["goal_id"] == goal.id]
    assert len(day2_titles) == 1
