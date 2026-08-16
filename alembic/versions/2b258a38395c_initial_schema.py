"""initial_schema

Revision ID: 2b258a38395c
Revises:
Create Date: 2026-08-16 21:47:10.871136

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2b258a38395c"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("openid", sa.String(length=64), nullable=False),
        sa.Column("unionid", sa.String(length=64), nullable=True),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("openid"),
    )

    op.create_table(
        "goals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("plan_start_date", sa.Date(), nullable=False),
        sa.Column("plan_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_wbs_generation_id", sa.BigInteger(), nullable=True),
        sa.Column("overall_progress_pct", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_index("ix_goals_active_wbs_generation_id", "goals", ["active_wbs_generation_id"])

    op.create_table(
        "wbs_generations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("llm_call_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "version", name="uq_wbs_goal_version"),
    )
    op.create_index("ix_wbs_generations_goal_id", "wbs_generations", ["goal_id"])
    op.create_index("ix_wbs_generations_user_id", "wbs_generations", ["user_id"])

    op.create_table(
        "task_nodes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("generation_id", sa.BigInteger(), nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_nodes_generation_id", "task_nodes", ["generation_id"])
    op.create_index("ix_task_nodes_goal_id", "task_nodes", ["goal_id"])
    op.create_index("ix_task_nodes_user_id", "task_nodes", ["user_id"])
    op.create_index("ix_task_nodes_parent_id", "task_nodes", ["parent_id"])

    op.create_table(
        "day_assignments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "task_id", "plan_date", name="uq_assign_goal_task_date"),
    )
    op.create_index("ix_day_assignments_goal_id", "day_assignments", ["goal_id"])
    op.create_index("ix_day_assignments_user_id", "day_assignments", ["user_id"])
    op.create_index("ix_day_assignments_task_id", "day_assignments", ["task_id"])

    op.create_table(
        "day_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("incomplete_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "work_date", name="uq_entry_task_date"),
    )
    op.create_index("ix_day_entries_goal_id", "day_entries", ["goal_id"])
    op.create_index("ix_day_entries_user_id", "day_entries", ["user_id"])
    op.create_index("ix_day_entries_task_id", "day_entries", ["task_id"])

    op.create_table(
        "deadline_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("old_end_date", sa.Date(), nullable=False),
        sa.Column("new_end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deadline_changes_goal_id", "deadline_changes", ["goal_id"])
    op.create_index("ix_deadline_changes_user_id", "deadline_changes", ["user_id"])

    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("goal_id", sa.BigInteger(), nullable=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("request_meta", sa.JSON(), nullable=True),
        sa.Column("response_meta", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_call_logs_user_id", "llm_call_logs", ["user_id"])
    op.create_index("ix_llm_call_logs_goal_id", "llm_call_logs", ["goal_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("goal_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_ref_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_goal_id", "jobs", ["goal_id"])

    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("biz_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_type", "biz_key", name="uq_job_run_type_key"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
    op.drop_index("ix_jobs_goal_id", table_name="jobs")
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_llm_call_logs_goal_id", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_user_id", table_name="llm_call_logs")
    op.drop_table("llm_call_logs")
    op.drop_index("ix_deadline_changes_user_id", table_name="deadline_changes")
    op.drop_index("ix_deadline_changes_goal_id", table_name="deadline_changes")
    op.drop_table("deadline_changes")
    op.drop_index("ix_day_entries_task_id", table_name="day_entries")
    op.drop_index("ix_day_entries_user_id", table_name="day_entries")
    op.drop_index("ix_day_entries_goal_id", table_name="day_entries")
    op.drop_table("day_entries")
    op.drop_index("ix_day_assignments_task_id", table_name="day_assignments")
    op.drop_index("ix_day_assignments_user_id", table_name="day_assignments")
    op.drop_index("ix_day_assignments_goal_id", table_name="day_assignments")
    op.drop_table("day_assignments")
    op.drop_index("ix_task_nodes_parent_id", table_name="task_nodes")
    op.drop_index("ix_task_nodes_user_id", table_name="task_nodes")
    op.drop_index("ix_task_nodes_goal_id", table_name="task_nodes")
    op.drop_index("ix_task_nodes_generation_id", table_name="task_nodes")
    op.drop_table("task_nodes")
    op.drop_index("ix_wbs_generations_user_id", table_name="wbs_generations")
    op.drop_index("ix_wbs_generations_goal_id", table_name="wbs_generations")
    op.drop_table("wbs_generations")
    op.drop_index("ix_goals_active_wbs_generation_id", table_name="goals")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
    op.drop_table("users")
