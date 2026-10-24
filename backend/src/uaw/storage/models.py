"""Database schema (SQLAlchemy ORM tables).

These classes describe tables only. The rest of the application works with domain
models (``uaw.domain``); ``store.py`` converts between the two.

Hierarchy: repository -> snapshot (one pinned commit) -> document (one file) -> chunk.
Deleting a parent deletes its children (``ON DELETE CASCADE``).
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# voyage-code-3 default output size. Changing it requires a migration and re-embedding.
EMBEDDING_DIMENSIONS = 1024

# Deterministic constraint names, so that migrations can refer to them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class RepositoryRow(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Lowercase "owner/name": GitHub names are case-insensitive, so this is the identity.
    key: Mapped[str] = mapped_column(String(200), unique=True)
    # Canonical casing, as reported by GitHub (for display and links).
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    default_branch: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SnapshotRow(Base):
    """A repository imported at one exact commit. Citations point into a snapshot."""

    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "commit_sha"),
        CheckConstraint("commit_sha ~ '^[0-9a-f]{40}$'", name="commit_sha_format"),
        CheckConstraint("status IN ('indexing', 'ready')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    commit_sha: Mapped[str] = mapped_column(String(40))
    # Only "ready" snapshots are searchable: an index is never used half-built.
    status: Mapped[str] = mapped_column(String(20), server_default="indexing")
    # Queries must be embedded with the same model as the documents.
    embedding_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path"),
        # Target of the composite foreign key on chunks (see ChunkRow).
        UniqueConstraint("id", "snapshot_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(50))
    # Lets a later import of the same file reuse its chunks and embeddings.
    content_sha256: Mapped[str] = mapped_column(String(64))


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # snapshot_id is denormalized so that searches can filter on it without a join.
        # The composite key guarantees it always equals the document's snapshot.
        ForeignKeyConstraint(
            ["document_id", "snapshot_id"],
            ["documents.id", "documents.snapshot_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_id", "ordinal"),
        CheckConstraint("start_line >= 1 AND end_line >= start_line", name="line_range"),
        Index("ix_chunks_snapshot_id", "snapshot_id"),
        # Approximate nearest-neighbour index for cosine distance (the `<=>` operator).
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Full-text search (the `@@` operator), see storage/fulltext.py.
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID]
    snapshot_id: Mapped[uuid.UUID]
    # Position of the chunk in its document (0, 1, 2...).
    ordinal: Mapped[int]
    start_line: Mapped[int]
    end_line: Mapped[int]
    section: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    # NULL until the ingestion pipeline computes it.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Words of the path, section and content, for full-text search. Computed when the
    # snapshot becomes ready (it needs the document's path).
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        # At most one active import per repository, enforced by the database even
        # if two requests arrive at the same time.
        Index(
            "uq_ingestion_jobs_active_repository",
            "repository_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Lowercase "owner/name", same identity as RepositoryRow.key.
    repository_key: Mapped[str] = mapped_column(String(200))
    # Canonical "owner/name" for display (GitHub's casing once known).
    repository: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str | None] = mapped_column(String(20))
    documents_count: Mapped[int] = mapped_column(server_default="0")
    skipped_count: Mapped[int] = mapped_column(server_default="0")
    chunks_count: Mapped[int] = mapped_column(server_default="0")
    embedded_count: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    reused_snapshot: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecordRow(Base):
    """Tokens used by one operation with one model. Kept when a repository is deleted:
    the usage was billed anyway."""

    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint("operation IN ('import', 'search', 'ask')", name="operation"),
        CheckConstraint("provider IN ('voyage', 'anthropic')", name="provider"),
        # Daily budgets sum one provider's tokens since midnight.
        Index("ix_usage_records_provider_created_at", "provider", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operation: Mapped[str] = mapped_column(String(20))
    # "owner/name" as requested by the client.
    repository: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    requests: Mapped[int]
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)


class BudgetReservationRow(Base):
    """Tokens set aside for an operation in progress, so that concurrent requests
    cannot all pass the budget check before any of them has recorded its usage.
    Deleted when the operation ends; ignored once expired (a crashed process)."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint("provider IN ('voyage', 'anthropic')", name="provider"),
        CheckConstraint("tokens > 0", name="tokens_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    tokens: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CachedAnswerRow(Base):
    """A suggested question with its answer, generated once (admin) and then served to
    every visitor without any model call. Tied to the snapshot it was answered from:
    deleting the snapshot deletes it, so a cached answer never outlives its sources."""

    __tablename__ = "cached_answers"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "language", "position"),
        CheckConstraint("language IN ('fr', 'en')", name="language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    # Language of the interface the question is suggested in.
    language: Mapped[str] = mapped_column(String(2))
    # Display order of the suggestions (0, 1, 2...).
    position: Mapped[int]
    question: Mapped[str] = mapped_column(Text)
    # The full answer as returned by POST /ask (text, citations, commit, model).
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
