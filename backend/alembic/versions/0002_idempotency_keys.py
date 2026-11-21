"""Idempotency keys and optimistic-concurrency etag versions (expand-only).

Revision ID: 0002_idempotency_keys
Revises: 0001_initial

Implements: T-080d
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_idempotency_keys"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``idempotency_keys`` and ``etag_version`` columns when missing."""
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "idempotency_keys" not in tables:
        op.create_table(
            "idempotency_keys",
            sa.Column("key", sa.Text(), primary_key=True),
            sa.Column("method", sa.Text(), nullable=False),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("body_sha256", sa.Text(), nullable=False),
            sa.Column("status", sa.Integer(), nullable=False),
            sa.Column("response_json", JSONB()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_idempotency_keys_created", "idempotency_keys", ["created_at"])

    for table in ("campaigns", "failure_modes"):
        cols = {c["name"] for c in inspector.get_columns(table)} if table in tables else set()
        if table in tables and "etag_version" not in cols:
            op.add_column(
                table,
                sa.Column(
                    "etag_version",
                    sa.Integer(),
                    server_default=sa.text("1"),
                    nullable=False,
                ),
            )


def downgrade() -> None:
    """Drop expand-only objects added in this revision."""
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table in ("campaigns", "failure_modes"):
        if table not in tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "etag_version" in cols:
            op.drop_column(table, "etag_version")
    if "idempotency_keys" in tables:
        op.drop_index("ix_idempotency_keys_created", table_name="idempotency_keys")
        op.drop_table("idempotency_keys")
