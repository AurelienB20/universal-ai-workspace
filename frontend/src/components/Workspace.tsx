"use client";

import { useCallback, useEffect, useState } from "react";

import { getConfig, listRepositories } from "@/lib/api";
import type { RepositorySummary } from "@/lib/types";

import { AskPanel } from "./AskPanel";
import { ImportPanel } from "./ImportPanel";
import { RepositoryPicker } from "./RepositoryPicker";

/** The whole flow: choose (or import) a repository, then ask questions about it. */
export function Workspace() {
  const [importsEnabled, setImportsEnabled] = useState(false);
  const [repositories, setRepositories] = useState<RepositorySummary[] | null>(null);
  const [listError, setListError] = useState<unknown>(null);
  // "owner/name" of the repository being questioned.
  const [repository, setRepository] = useState<string | null>(null);

  const loadRepositories = useCallback(async () => {
    try {
      const items = await listRepositories();
      setRepositories(items);
      setListError(null);
      return items;
    } catch (caught) {
      setListError(caught);
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      // A demo without imports is the safe default if the config cannot be read.
      const config = await getConfig().catch(() => ({ importsEnabled: false }));
      if (!cancelled) setImportsEnabled(config.importsEnabled);
      const items = await loadRepositories();
      // One repository only (a typical demo): select it directly.
      if (!cancelled && items?.length === 1) setRepository(items[0].repository);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadRepositories]);

  const onImported = useCallback(
    (imported: string | null) => {
      if (imported === null) return;
      setRepository(imported);
      void loadRepositories(); // the new repository joins the list
    },
    [loadRepositories],
  );

  return (
    <div className="flex flex-col gap-6">
      <RepositoryPicker
        repositories={repositories}
        error={listError}
        selected={repository}
        onSelect={setRepository}
      />
      {importsEnabled && <ImportPanel onReady={onImported} />}
      {/* Keyed: changing repository starts a fresh conversation. */}
      {repository && <AskPanel key={repository} repository={repository} />}
    </div>
  );
}
