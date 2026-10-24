"use client";

import { errorMessage } from "@/i18n/errors";
import { useLanguage } from "@/i18n/language";
import type { RepositorySummary } from "@/lib/types";

interface Props {
  /** null while loading. */
  repositories: RepositorySummary[] | null;
  error: unknown;
  selected: string | null;
  onSelect: (repository: string) => void;
}

/** The repositories this interface can question (GET /repositories). */
export function RepositoryPicker({ repositories, error, selected, onSelect }: Props) {
  const { t } = useLanguage();

  return (
    <section className="card">
      <h2 className="card-title">{t.repoHeading}</h2>
      <p className="mb-2 text-sm font-medium">{t.repositoriesLabel}</p>

      {error !== null ? (
        <p role="alert" className="error">
          {errorMessage(error, t, "ask")}
        </p>
      ) : repositories === null ? (
        <p className="animate-pulse text-sm text-zinc-500">{t.loadingRepositories}</p>
      ) : repositories.length === 0 ? (
        <p className="text-sm text-zinc-500">{t.noRepositories}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {repositories.map((item) => {
            const active = item.repository.toLowerCase() === selected?.toLowerCase();
            return (
              <li key={item.repository}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelect(item.repository)}
                  className={`flex w-full flex-col items-start rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    active
                      ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/50"
                      : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50"
                  }`}
                >
                  <span className="font-semibold">{item.repository}</span>
                  <span className="text-xs text-zinc-500">
                    {t.repositoryMeta(item.documents_count, item.commit_sha.slice(0, 7))}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
