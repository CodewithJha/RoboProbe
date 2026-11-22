"""Persist report job state and experiment notes (T-084a, T-112b).

Revision ID: report_jobs_state
Revises: 0003_mode_duplicates
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "report_jobs_state"
down_revision: str | Sequence[str] | None = "0003_mode_duplicates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add job records and concurrency metadata for experiment notes."""
    inspector = inspect(op.get_bind())
    if "report_jobs" not in inspector.get_table_names():
        op.create_table(
            "report_jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("target_id", sa.Uuid(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("html_path", sa.Text()),
        )
    columns = {column["name"] for column in inspector.get_columns("experiments")}
    if "notes" not in columns:
        op.add_column(
            "experiments", sa.Column("notes", sa.Text(), nullable=False, server_default="")
        )
    if "etag_version" not in columns:
        op.add_column(
            "experiments",
            sa.Column("etag_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    """Remove report jobs and experiment notes metadata."""
    op.drop_column("experiments", "etag_version")
    op.drop_column("experiments", "notes")
    op.drop_table("report_jobs")
