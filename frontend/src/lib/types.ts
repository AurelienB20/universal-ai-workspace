// Shapes of the backend responses (see backend/src/uaw/domain/jobs.py and
// backend/src/uaw/generation/answerer.py).

export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type JobStage = "fetching" | "chunking" | "embedding" | "done";

export interface ImportJob {
  id: string;
  repository: string;
  status: JobStatus;
  stage: JobStage | null;
  documents_count: number;
  skipped_count: number;
  chunks_count: number;
  embedded_count: number;
  error: string | null;
  snapshot_id: string | null;
  reused_snapshot: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Citation {
  id: string; // "S1", "S2"...
  path: string;
  start_line: number;
  end_line: number;
  url: string;
}

export interface Answer {
  repository: string;
  commit_sha: string;
  answer: string; // Markdown citing [S1], [S2]...
  insufficient_context: boolean;
  citations: Citation[];
  model: string | null;
}
