"""The visitor of the public demo who asked for each import (None: the admin).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("visitor_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "visitor_id")
