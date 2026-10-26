"""Repositories imported by visitors of the public demo, each readable by its visitor only.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visitor_repositories",
        sa.Column("visitor_id", sa.Uuid(), nullable=False),
        sa.Column("repository_key", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "visitor_id", "repository_key", name=op.f("pk_visitor_repositories")
        ),
    )
    op.create_index("ix_visitor_repositories_expires_at", "visitor_repositories", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_visitor_repositories_expires_at", table_name="visitor_repositories")
    op.drop_table("visitor_repositories")
