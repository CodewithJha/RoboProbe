"""Initial schema (docs/11 §3).

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from roboprobe.store.orm import Base

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create every table in docs/11 §3 from ORM metadata."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop the initial schema."""
    Base.metadata.drop_all(bind=op.get_bind())
