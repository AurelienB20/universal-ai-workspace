"""Token usage records, for cost tracking and daily budgets.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("repository", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "operation IN ('import', 'search', 'ask')", name=op.f("ck_usage_records_operation")
        ),
        sa.CheckConstraint(
            "provider IN ('voyage', 'anthropic')", name=op.f("ck_usage_records_provider")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(
        "ix_usage_records_provider_created_at", "usage_records", ["provider", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("usage_records")  # also drops its index
