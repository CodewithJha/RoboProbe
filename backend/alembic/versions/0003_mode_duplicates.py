"""Store duplicate links for failure modes (T-110a).

Revision ID: 0003_mode_duplicates
Revises: 0002_idempotency_keys
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_mode_duplicates"
down_revision = "0002_idempotency_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an optional casebook duplicate link without rewriting existing modes."""
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("failure_modes")}
    if "duplicate_of" not in columns:
        op.add_column("failure_modes", sa.Column("duplicate_of", sa.Text()))


def downgrade() -> None:
    """Remove the optional casebook duplicate link."""
    op.drop_column("failure_modes", "duplicate_of")
