"use client";

import { useEffect, useState } from "react";

import { errorMessage } from "@/i18n/errors";
import { useLanguage } from "@/i18n/language";
import { getImport, startImport } from "@/lib/api";
import type { ImportJob } from "@/lib/types";

const POLL_INTERVAL_MS = 1500;

function isActive(job: ImportJob | null): boolean {
  return job?.status === "queued" || job?.status === "running";
}

interface Props {
  /** Imports by a visitor of a public demo: private, temporary and limited. */
  visitor: boolean;
  /** Called with "owner/name" once the repository is searchable, null when reset. */
  onReady: (repository: string | null) => void;
}

export function ImportPanel({ visitor, onReady }: Props) {
  const { t } = useLanguage();
  const [url, setUrl] = useState("");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Follow the job until it ends. Polling stops when the panel is reset or unmounted.
  useEffect(() => {
    if (job === null || !isActive(job)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const next = await getImport(job.id);
        if (cancelled) return;
        setJob(next);
        if (next.status === "succeeded") onReady(next.repository);
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught, t, "import"));
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [job, onReady, t]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const started = await startImport(url.trim());
      setJob(started);
      if (started.status === "succeeded") onReady(started.repository);
    } catch (caught) {
      setError(errorMessage(caught, t, "import"));
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    setJob(null);
    setError(null);
    onReady(null);
  }

  const locked = submitting || isActive(job) || job?.status === "succeeded";

  return (
    <section className="card">
      <h2 className="card-title">{visitor ? t.publicImportHeading : t.importHeading}</h2>
      {visitor && <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">{t.publicImportNotice}</p>}

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">{t.repoLabel}</span>
          <input
            type="url"
            required
            maxLength={1000}
            value={url}
            disabled={locked}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://github.com/pallets/itsdangerous"
            className="input"
          />
        </label>
        {job?.status === "succeeded" ? (
          <button type="button" onClick={reset} className="button-secondary">
            {t.changeRepo}
          </button>
        ) : (
          <button type="submit" disabled={locked} className="button-primary">
            {locked ? t.importing : t.importButton}
          </button>
        )}
      </form>

      {job && <JobStatus job={job} />}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}

function JobStatus({ job }: { job: ImportJob }) {
  const { t } = useLanguage();

  if (job.status === "failed") {
    return (
      <p role="alert" className="error">
        {t.importFailed(job.error ?? "")}
      </p>
    );
  }
  if (job.status === "succeeded") {
    return (
      <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">
        ✓ <strong>{job.repository}</strong> — {t.importSummary(job.documents_count, job.chunks_count)}
        {job.reused_snapshot && ` (${t.reusedIndex})`}
      </p>
    );
  }

  const stage = job.status === "queued" ? t.stages.queued : t.stages[job.stage ?? "fetching"];
  const embedding = job.stage === "embedding" && job.chunks_count > 0;
  const percent = embedding ? Math.round((job.embedded_count / job.chunks_count) * 100) : null;

  return (
    <div className="mt-3 flex flex-col gap-2 text-sm" aria-live="polite">
      <p className="text-zinc-600 dark:text-zinc-400">
        {stage}…{embedding && ` ${t.embeddedProgress(job.embedded_count, job.chunks_count)}`}
      </p>
      <div
        role="progressbar"
        aria-valuenow={percent ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
      >
        <div
          className={`h-full rounded-full bg-indigo-600 transition-all ${percent === null ? "w-1/3 animate-pulse" : ""}`}
          style={percent === null ? undefined : { width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
