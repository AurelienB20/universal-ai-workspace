"use client";

import { useState } from "react";

import {
  type ArchitectureContent,
  STEP_CODE,
  STEP_IDS,
  type StepId,
  codeUrl,
} from "@/i18n/architecture";

// The first four steps run once per import, the others for every question.
const IMPORT_STEPS = new Set<StepId>(["import", "read", "chunk", "embed"]);

export function PipelineExplorer({ content }: { content: ArchitectureContent["pipeline"] }) {
  const [selected, setSelected] = useState<StepId>("import");
  const step = content.steps[selected];
  const index = STEP_IDS.indexOf(selected);
  const { labels } = content;

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      <ol className="flex shrink-0 flex-col gap-1.5 md:w-64" aria-label={content.heading}>
        {STEP_IDS.map((id, position) => {
          const active = id === selected;
          return (
            <li key={id}>
              <button
                type="button"
                aria-pressed={active}
                onClick={() => setSelected(id)}
                className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                  active
                    ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/50"
                    : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50"
                }`}
              >
                <span
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    IMPORT_STEPS.has(id)
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                      : "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300"
                  }`}
                >
                  {position + 1}
                </span>
                <span className="flex flex-col">
                  <span className="text-sm font-semibold">{content.steps[id].title}</span>
                  <span className="text-xs text-zinc-500">{content.steps[id].short}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <article
        aria-live="polite"
        className="flex flex-1 flex-col gap-4 rounded-xl border border-zinc-200 p-5 dark:border-zinc-800"
      >
        <header>
          <p className="text-xs font-semibold tracking-wide text-indigo-600 uppercase dark:text-indigo-400">
            {labels.step(index + 1, STEP_IDS.length)}
          </p>
          <h3 className="text-xl font-semibold">{step.title}</h3>
        </header>

        <section>
          <h4 className="mb-1 text-sm font-semibold">{labels.what}</h4>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
            {step.what.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>

        <section className="rounded-lg bg-indigo-50 px-4 py-3 dark:bg-indigo-950/40">
          <h4 className="mb-1 text-sm font-semibold text-indigo-800 dark:text-indigo-300">
            {labels.choice}
          </h4>
          <p className="text-sm">{step.choice}</p>
        </section>

        <section>
          <h4 className="mb-1 text-sm font-semibold">{labels.alternatives}</h4>
          <ul className="flex flex-col gap-2 text-sm">
            {step.alternatives.map((alternative) => (
              <li key={alternative.name} className="flex gap-2">
                <span aria-hidden="true" className="text-zinc-400">
                  ✕
                </span>
                <span>
                  <strong className="font-medium">{alternative.name}</strong>
                  <span className="text-zinc-600 dark:text-zinc-400"> — {alternative.why}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <div className="flex flex-col gap-3 border-t border-zinc-200 pt-3 text-sm sm:flex-row sm:justify-between dark:border-zinc-800">
          {/* Label on its own line: "X : y" and "X: y" differ between French and English. */}
          <p className="flex flex-col gap-0.5">
            <span className="font-semibold">{labels.figure}</span>
            <span className="text-zinc-700 dark:text-zinc-300">{step.figure}</span>
          </p>
          <div className="flex shrink-0 flex-col gap-0.5">
            <span className="font-semibold">{labels.code}</span>
            {STEP_CODE[selected].map((path) => (
              <a
                key={path}
                href={codeUrl(path)}
                target="_blank"
                rel="noopener noreferrer"
                className="link font-mono text-xs"
              >
                {path.split("/").slice(-2).join("/")} ↗
              </a>
            ))}
          </div>
        </div>
      </article>
    </div>
  );
}
