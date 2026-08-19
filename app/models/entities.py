from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# SQLite 仅对 INTEGER PK 自增；生产可用 BIGINT
PK = BigInteger().with_variant(Integer, "sqlite")
FK = BigInteger().with_variant(Integer, "sqlite")


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    plan_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    active_wbs_generation_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    overall_progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WbsGeneration(Base):
    __tablename__ = "wbs_generations"
    __table_args__ = (UniqueConstraint("goal_id", "version", name="uq_wbs_goal_version"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # suggested/active/...
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai")
    llm_call_id: Mapped[int | None] = mapped_column(FK, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskNode(Base):
    __tablename__ = "task_nodes"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    generation_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    goal_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # milestone|task
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    depends_on_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


class DayAssignment(Base):
    __tablename__ = "day_assignments"
    __table_args__ = (
        UniqueConstraint("goal_id", "task_id", "plan_date", name="uq_assign_goal_task_date"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


class DayEntry(Base):
    __tablename__ = "day_entries"
    __table_args__ = (UniqueConstraint("task_id", "work_date", name="uq_entry_task_date"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    incomplete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)


class DeadlineChange(Base):
    __tablename__ = "deadline_changes"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(FK, nullable=False, index=True)
    old_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    job_id: Mapped[int | None] = mapped_column(FK, nullable=True)
    applied_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(FK, nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    result_ref_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, onupdate=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_type", "biz_key", name="uq_job_run_type_key"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
