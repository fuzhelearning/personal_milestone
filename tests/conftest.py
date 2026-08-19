"""Shared fixtures for LLM unit tests (in-memory SQLite)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Goal, TaskNode, User, WbsGeneration


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def user(db: Session) -> User:
    u = User(openid="test-openid", timezone="Asia/Shanghai")
    db.add(u)
    db.flush()
    return u


def make_goal(
    db: Session,
    user: User,
    *,
    start: date | None = None,
    end: date | None = None,
    title: str = "测试目标",
) -> Goal:
    start = start or date(2026, 8, 1)
    end = end or date(2026, 8, 3)
    g = Goal(
        user_id=user.id,
        title=title,
        note="备注",
        plan_start_date=start,
        plan_end_date=end,
        status="draft",
    )
    db.add(g)
    db.flush()
    return g


def seed_active_wbs(
    db: Session,
    goal: Goal,
    *,
    task_count: int = 3,
) -> list[TaskNode]:
    gen = WbsGeneration(
        goal_id=goal.id,
        user_id=goal.user_id,
        version=1,
        status="active",
        source="ai",
    )
    db.add(gen)
    db.flush()
    goal.active_wbs_generation_id = gen.id
    goal.status = "active"

    mil = TaskNode(
        generation_id=gen.id,
        goal_id=goal.id,
        user_id=goal.user_id,
        parent_id=None,
        kind="milestone",
        code="1.0",
        title="阶段",
        sort_order=0,
        start_date=goal.plan_start_date,
        end_date=goal.plan_end_date,
    )
    db.add(mil)
    db.flush()

    tasks: list[TaskNode] = []
    for i in range(task_count):
        t = TaskNode(
            generation_id=gen.id,
            goal_id=goal.id,
            user_id=goal.user_id,
            parent_id=mil.id,
            kind="task",
            code=f"1.{i + 1}",
            title=f"任务{i + 1}",
            sort_order=i,
            start_date=goal.plan_start_date,
            end_date=goal.plan_end_date,
            progress_pct=0,
        )
        db.add(t)
        tasks.append(t)
    db.flush()
    return tasks
