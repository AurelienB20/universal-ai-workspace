import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# A repository can have at most one job in these states at a time.
ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class JobStage(StrEnum):
    FETCHING = "fetching"  # downloading the repository from GitHub
    CHUNKING = "chunking"  # splitting files and saving chunks
    EMBEDDING = "embedding"  # computing embeddings, batch by batch
    DONE = "done"


class IngestionJob(BaseModel):
    """Progress of one repository import, as shown to users."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    repository: str  # "owner/name"
    status: JobStatus
    stage: JobStage | None
    documents_count: int
    skipped_count: int
    chunks_count: int
    embedded_count: int
    # User-facing message, set when the job failed.
    error: str | None
    snapshot_id: uuid.UUID | None
    # True when this commit was already indexed and the existing snapshot was reused.
    reused_snapshot: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
