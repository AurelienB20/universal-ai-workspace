"""Database schema (SQLAlchemy ORM tables).

These classes describe tables only. The rest of the application works with domain
models (``uaw.domain``); ``store.py`` converts between the two.

Hierarchy: repository -> snapshot (one pinned commit) -> document (one file) -> chunk.
Deleting a parent deletes its children (``ON DELETE CASCADE``).
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    commit_sha: Mapped[str] = mapped_column(String(40))
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
