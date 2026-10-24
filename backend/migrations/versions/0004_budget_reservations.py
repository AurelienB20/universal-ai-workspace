"""Budget reservations: tokens set aside by the operations in progress.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('voyage', 'anthropic')", name=op.f("ck_budget_reservations_provider")
        ),
        sa.CheckConstraint("tokens > 0", name=op.f("ck_budget_reservations_tokens_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_reservations")),
    )


def downgrade() -> None:
    op.drop_table("budget_reservations")
