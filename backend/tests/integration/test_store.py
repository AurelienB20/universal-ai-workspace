import math
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.chunking.chunker import chunk_document
from uaw.chunking.lines import ChunkingConfig
from uaw.connectors.github.client import RepositoryInfo
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument
from uaw.storage.models import EMBEDDING_DIMENSIONS, ChunkRow, DocumentRow, RepositoryRow
from uaw.storage.store import (
    SnapshotAlreadyExistsError,
    SnapshotInfo,
    SnapshotStatus,
    SnapshotStore,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]

SHA_A = "a" * 40
SHA_B = "b" * 40
MODEL = "voyage-code-3"
CONFIG = ChunkingConfig(max_chars=200, min_chars=50, overlap_lines=1)

DOCUMENTS = [
    SourceDocument(
        path="src/app.py",
        language="python",
        content="".join(f"def handler_{i}(request):\n    return {i}\n\n\n" for i in range(12)),
    ),
    SourceDocument(
        path="README.md",
        language="markdown",
        content="# Demo\n\nIntro.\n\n## Install\n\nRun `make`.\n",
    ),
]


def repository_info(
    owner: str = "Pallets", name: str = "Flask", branch: str = "main"
) -> RepositoryInfo:
    return RepositoryInfo(
        ref=GitHubRepoRef(owner=owner, name=name),
        default_branch=branch,
        size_kb=1,
        private=False,
        description=None,
    )


def unit_vector(axis: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[axis] = 1.0
    return vector


async def import_snapshot(store: SnapshotStore, sha: str = SHA_A) -> uuid.UUID:
    repository_id = await store.upsert_repository(repository_info())
    snapshot_id = await store.create_snapshot(repository_id, sha, embedding_model=MODEL)
    for document in DOCUMENTS:
        await store.add_document(snapshot_id, document, chunk_document(document, CONFIG))
    return snapshot_id


async def count(session: AsyncSession, table: type[object]) -> int:
    return (await session.execute(select(func.count()).select_from(table))).scalar_one()


async def test_upsert_repository_is_idempotent_and_case_insensitive(
    session: AsyncSession,
) -> None:
    store = SnapshotStore(session)

    first = await store.upsert_repository(repository_info("pallets", "flask", "main"))
    second = await store.upsert_repository(repository_info("Pallets", "Flask", "develop"))

    assert first == second
    row = (await session.execute(select(RepositoryRow))).scalar_one()
    # Metadata is refreshed with the latest values reported by GitHub.
    assert (row.owner, row.name, row.default_branch) == ("Pallets", "Flask", "develop")


async def test_chunks_round_trip_exactly(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    snapshot_id = await import_snapshot(store)
    await session.commit()

    stored = await store.list_chunks(snapshot_id)

    expected = [
        chunk
        for doc in sorted(DOCUMENTS, key=lambda d: d.path)
        for chunk in chunk_document(doc, CONFIG)
    ]
    assert len(expected) > 2  # the sample really is split into several chunks
    assert [item.chunk for item in stored] == expected
    assert len({item.id for item in stored}) == len(stored)


async def test_same_commit_cannot_be_imported_twice(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    repository_id = await store.upsert_repository(repository_info())
    snapshot_id = await store.create_snapshot(repository_id, SHA_A, embedding_model=MODEL)

    with pytest.raises(SnapshotAlreadyExistsError):
        await store.create_snapshot(repository_id, SHA_A, embedding_model=MODEL)

    # The transaction is still usable: no failed statement aborted it.
    assert await store.find_snapshot(repository_id, SHA_A) == SnapshotInfo(
        id=snapshot_id, status=SnapshotStatus.INDEXING, embedding_model=MODEL
    )
    assert await store.find_snapshot(repository_id, SHA_B) is None
    await store.create_snapshot(repository_id, SHA_B, embedding_model=MODEL)


async def test_snapshot_becomes_ready_only_when_fully_embedded(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    snapshot_id = await import_snapshot(store)
    chunk_ids = [item.id for item in await store.list_chunks(snapshot_id)]

    await store.set_embeddings({chunk_id: unit_vector(0) for chunk_id in chunk_ids[1:]})
    with pytest.raises(ValueError, match="1 chunks"):
        await store.mark_snapshot_ready(snapshot_id)

    await store.set_embeddings({chunk_ids[0]: unit_vector(0)})
    await store.mark_snapshot_ready(snapshot_id)
    repository_id = await store.upsert_repository(repository_info())
    snapshot = await store.find_snapshot(repository_id, SHA_A)
    assert snapshot is not None and snapshot.status is SnapshotStatus.READY


async def test_database_rejects_malformed_commit_sha(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    repository_id = await store.upsert_repository(repository_info())

    with pytest.raises(IntegrityError, match="commit_sha_format"):
        await store.create_snapshot(repository_id, "A" * 40, embedding_model=MODEL)


async def test_database_rejects_duplicate_path_in_a_snapshot(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    snapshot_id = await import_snapshot(store)

    with pytest.raises(IntegrityError, match="uq_documents_snapshot_id_path"):
        await store.add_document(snapshot_id, DOCUMENTS[0], [])


async def test_chunks_must_belong_to_their_document(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    repository_id = await store.upsert_repository(repository_info())
    snapshot_id = await store.create_snapshot(repository_id, SHA_A, embedding_model=MODEL)
    foreign = Chunk(path="other.py", language="python", start_line=1, end_line=1, content="x\n")

    with pytest.raises(ValueError, match=r"src/app\.py"):
        await store.add_document(snapshot_id, DOCUMENTS[0], [foreign])


async def test_chunk_snapshot_must_match_its_document(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    snapshot_a = await import_snapshot(store, SHA_A)
    repository_id = await store.upsert_repository(repository_info())
    snapshot_b = await store.create_snapshot(repository_id, SHA_B, embedding_model=MODEL)
    document_id = (
        (await session.execute(select(DocumentRow.id).where(DocumentRow.snapshot_id == snapshot_a)))
        .scalars()
        .first()
    )

    # The composite foreign key forbids a chunk pointing to a document of another snapshot.
    session.add(
        ChunkRow(
            id=uuid.uuid4(),
            document_id=document_id,
            snapshot_id=snapshot_b,
            ordinal=99,
            start_line=1,
            end_line=1,
            content="x\n",
        )
    )
    with pytest.raises(IntegrityError, match="fk_chunks_document_id_snapshot_id_documents"):
        await session.flush()


async def test_embeddings_are_stored_and_searchable_by_cosine_distance(
    session: AsyncSession,
) -> None:
    store = SnapshotStore(session)
    snapshot_id = await import_snapshot(store)
    chunk_ids = [item.id for item in await store.list_chunks(snapshot_id)]
    await store.set_embeddings({chunk_id: unit_vector(i) for i, chunk_id in enumerate(chunk_ids)})

    # Closest to axis 2, then a little towards axis 0.
    query = [0.0] * EMBEDDING_DIMENSIONS
    query[2], query[0] = 1.0, 0.3
    distance = ChunkRow.embedding.cosine_distance(query)
    rows = (await session.execute(select(ChunkRow.id, distance).order_by(distance).limit(2))).all()

    assert [row.id for row in rows] == [chunk_ids[2], chunk_ids[0]]
    assert math.isclose(rows[0][1], 1 - 1 / math.sqrt(1.09), rel_tol=1e-6)


async def test_embedding_dimension_is_checked(session: AsyncSession) -> None:
    store = SnapshotStore(session)

    with pytest.raises(ValueError, match="1024"):
        await store.set_embeddings({uuid.uuid4(): [0.1, 0.2]})


async def test_delete_snapshot_cascades_to_documents_and_chunks(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    kept = await import_snapshot(store, SHA_A)
    deleted = await import_snapshot(store, SHA_B)
    kept_chunks = await count(session, ChunkRow) // 2

    assert await store.delete_snapshot(deleted) is True
    assert await store.delete_snapshot(deleted) is False

    assert await store.list_chunks(deleted) == []
    assert len(await store.list_chunks(kept)) == kept_chunks
    assert await count(session, DocumentRow) == len(DOCUMENTS)


async def test_rolled_back_import_leaves_nothing(session: AsyncSession) -> None:
    store = SnapshotStore(session)
    await import_snapshot(store)

    await session.rollback()

    assert await count(session, RepositoryRow) == 0
    assert await count(session, ChunkRow) == 0
    assert (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one() == 0
