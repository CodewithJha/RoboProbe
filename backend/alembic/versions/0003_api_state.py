"""Durable report jobs and mode duplicate links (T-082a, T-084a).

Revision ID: 0003_api_state
Revises: 0002_idempotency_keys
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_api_state"
down_revision: str | Sequence[str] | None = "0002_idempotency_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expand API persistence without rewriting existing records."""
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
    columns = {column["name"] for column in inspector.get_columns("failure_modes")}
    if "duplicate_of" not in columns:
        op.add_column("failure_modes", sa.Column("duplicate_of", sa.Text()))

    exp_columns = {column["name"] for column in inspector.get_columns("experiments")}
    if "notes" not in exp_columns:
        op.add_column(
            "experiments", sa.Column("notes", sa.Text(), nullable=False, server_default="")
        )
    if "etag_version" not in exp_columns:
        op.add_column(
            "experiments",
            sa.Column("etag_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    """Remove API job state and duplicate links."""
    op.drop_column("failure_modes", "duplicate_of")
    op.drop_table("report_jobs")
    op.drop_column("experiments", "notes")
    op.drop_column("experiments", "etag_version")
