"use client";

import { useState } from "react";

import { AskPanel } from "./AskPanel";
import { ImportPanel } from "./ImportPanel";

/** The whole flow: choose a repository, then ask questions about it. */
export function Workspace() {
  // "owner/name" once the repository is imported and searchable.
  const [repository, setRepository] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-6">
      <ImportPanel onReady={setRepository} />
      {/* Keyed: changing repository starts a fresh conversation. */}
      {repository && <AskPanel key={repository} repository={repository} />}
    </div>
  );
}
