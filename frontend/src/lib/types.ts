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

// A passage shown to the model, in retrieval order.
export interface Passage {
  id: string;
  path: string;
  start_line: number;
  end_line: number;
  section: string | null;
  content: string;
  score: number; // cosine similarity with the question
  rerank_score?: number | null; // relevance from the reranker, when one ordered them
  url: string;
}

export interface RetrievedPassage extends Passage {
  cited: boolean;
}

// How the answer was built (backend/src/uaw/generation/answerer.py).
export interface AnswerTrace {
  passages: RetrievedPassage[];
  removed_citations: string[]; // cited by the model without having been provided
  retrieval_ms: number;
  generation_ms: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Answer {
  repository: string;
  commit_sha: string;
  answer: string; // Markdown citing [S1], [S2]...
  insufficient_context: boolean;
  citations: Citation[];
  model: string | null;
  trace?: AnswerTrace | null; // absent from answers cached before traces existed
}

// First event of a streamed answer (POST /ask/stream): the passages it is written from.
export interface SourcesFound {
  repository: string;
  commit_sha: string;
  passages: Passage[];
}

// backend/src/uaw/storage/repositories.py
export interface RepositorySummary {
  repository: string; // "Owner/Name"
  default_branch: string;
  commit_sha: string;
  indexed_at: string;
  documents_count: number;
  chunks_count: number;
  // End of the visitor's access to a repository they imported; null for the others.
  expires_at: string | null;
}

// backend/src/uaw/storage/cached_answers.py and api/repositories.py
export interface CachedAnswer {
  question: string;
  answer: Answer;
  generated_at: string;
}

export interface Suggestions {
  repository: string;
  commit_sha: string;
  language: "fr" | "en";
  items: CachedAnswer[];
}

// app/api/config/route.ts
export interface InterfaceConfig {
  importsEnabled: boolean;
  // Imports by visitors of a public demo: private to each visitor, and temporary.
  publicImports: boolean;
}
