"""Ingestion jobs, snapshot status and embedding model.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 22:56:46.050126
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Snapshots created before this migration were never embedded: they stay
    # "indexing" (not searchable) and the next import of their commit redoes them.
    op.add_column(
        "snapshots",
        sa.Column("status", sa.String(length=20), server_default="indexing", nullable=False),
    )
    op.create_check_constraint("status", "snapshots", "status IN ('indexing', 'ready')")
    # Added nullable, backfilled with the only model used so far, then made NOT NULL,
    # so that the migration also works on a database that already has snapshots.
    op.add_column("snapshots", sa.Column("embedding_model", sa.String(length=100)))
    op.execute("UPDATE snapshots SET embedding_model = 'voyage-code-3'")
    op.alter_column("snapshots", "embedding_model", nullable=False)

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_key", sa.String(length=200), nullable=False),
        sa.Column("repository", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("documents_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("reused_snapshot", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_ingestion_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_ingestion_jobs_snapshot_id_snapshots"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        "uq_ingestion_jobs_active_repository",
        "ingestion_jobs",
        ["repository_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_jobs")  # also drops its index
    op.drop_column("snapshots", "embedding_model")
    op.drop_column("snapshots", "status")  # also drops its check constraint
