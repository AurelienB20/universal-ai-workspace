"""Full-text search on chunks: a tsvector column with a GIN index, filled for every chunk.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same expression as uaw.storage.fulltext.CHUNK_SEARCH_VECTOR_SQL when this migration was
# written. Copied rather than imported: a migration must not change when the code does.
CHUNK_SEARCH_VECTOR_SQL = """
    setweight(to_tsvector('simple', regexp_replace(d.path, '[/._-]+', ' ', 'g')), 'A')
    || setweight(to_tsvector('simple', coalesce(c.section, '')), 'B')
    || setweight(to_tsvector('simple', c.content), 'C')
    || setweight(to_tsvector('simple', array_to_string(ARRAY(
        SELECT replace(m[1], '_', '')
        FROM regexp_matches(c.content, '([A-Za-z0-9]+(_[A-Za-z0-9]+)+)', 'g') AS m
    ), ' ')), 'C')
"""


def upgrade() -> None:
    op.add_column("chunks", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    # Existing snapshots stay searchable by text without being imported again.
    op.execute(
        f"UPDATE chunks AS c SET search_vector = {CHUNK_SEARCH_VECTOR_SQL} "
        "FROM documents AS d WHERE d.id = c.document_id"
    )
    op.create_index("ix_chunks_search_vector", "chunks", ["search_vector"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_search_vector", table_name="chunks")
    op.drop_column("chunks", "search_vector")
