"""add applied_end_date to deadline_changes

Revision ID: 3c1a9f2b0e4d
Revises: 2b258a38395c
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "3c1a9f2b0e4d"
down_revision = "2b258a38395c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deadline_changes",
        sa.Column("applied_end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deadline_changes", "applied_end_date")
