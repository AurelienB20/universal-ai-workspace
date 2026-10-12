"""Initial schema: repositories, snapshots, documents and chunks with embeddings.

Revision ID: 0001
Revises:
Create Date: 2026-10-12 22:39:23.045503
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector provides the `vector` type, the `<=>` operator and HNSW indexes.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("key", name=op.f("uq_repositories_key")),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}$'", name=op.f("ck_snapshots_commit_sha_format")
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_snapshots_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
        sa.UniqueConstraint(
            "repository_id", "commit_sha", name=op.f("uq_snapshots_repository_id_commit_sha")
        ),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_documents_snapshot_id_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("id", "snapshot_id", name=op.f("uq_documents_id_snapshot_id")),
        sa.UniqueConstraint("snapshot_id", "path", name=op.f("uq_documents_snapshot_id_path")),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.CheckConstraint(
            "start_line >= 1 AND end_line >= start_line", name=op.f("ck_chunks_line_range")
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "snapshot_id"],
            ["documents.id", "documents.snapshot_id"],
            name=op.f("fk_chunks_document_id_snapshot_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("document_id", "ordinal", name=op.f("uq_chunks_document_id_ordinal")),
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_snapshot_id", "chunks", ["snapshot_id"])


def downgrade() -> None:
    op.drop_table("chunks")  # also drops its indexes
    op.drop_table("documents")
    op.drop_table("snapshots")
    op.drop_table("repositories")
    # The `vector` extension is kept: other objects in the database may depend on it.
