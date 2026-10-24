"use client";

import { useLanguage } from "@/i18n/language";
import { lineRange } from "@/lib/citations";
import { scoreWidths } from "@/lib/evidence";
import type { AnswerTrace } from "@/lib/types";

/** "Explain the Evidence": the passages behind an answer, and what the server checked. */
export function EvidencePanel({ trace }: { trace: AnswerTrace }) {
  const { t } = useLanguage();
  const number = new Intl.NumberFormat(t.dateLocale);
  const seconds = new Intl.NumberFormat(t.dateLocale, { maximumFractionDigits: 1 });
  const duration = (ms: number) => `${seconds.format(ms / 1000)} s`;
  const cited = trace.passages.filter((passage) => passage.cited).length;
  const widths = scoreWidths(trace.passages);

  return (
    // <details>: closed by default, accessible, and no state to keep.
    <details className="group rounded-lg border border-zinc-200 text-sm dark:border-zinc-800">
      <summary className="cursor-pointer list-none px-3 py-2 font-medium text-indigo-700 select-none hover:bg-zinc-50 dark:text-indigo-300 dark:hover:bg-zinc-800/50">
        <span className="mr-1 inline-block transition-transform group-open:rotate-90">▸</span>
        {t.evidence.toggle}
      </summary>

      <div className="flex flex-col gap-3 border-t border-zinc-200 px-3 py-3 dark:border-zinc-800">
        <p className="text-zinc-600 dark:text-zinc-400">{t.evidence.intro}</p>

        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
          <li>{t.evidence.summary(trace.passages.length, cited)}</li>
          <li>{t.evidence.timings(duration(trace.retrieval_ms), duration(trace.generation_ms))}</li>
          <li>
            {t.evidence.tokens(number.format(trace.input_tokens), number.format(trace.output_tokens))}
          </li>
        </ul>

        {trace.removed_citations.length > 0 && (
          <p className="notice">{t.evidence.removed(trace.removed_citations)}</p>
        )}

        <ol className="flex flex-col gap-2">
          {trace.passages.map((passage, index) => (
            <li
              key={passage.id}
              className={`rounded-md border px-3 py-2 ${
                passage.cited
                  ? "border-indigo-300 bg-indigo-50/60 dark:border-indigo-800 dark:bg-indigo-950/30"
                  : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="citation">{passage.id}</span>
                <a
                  href={passage.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link font-mono text-xs break-all"
                >
                  {lineRange(passage)}
                </a>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    passage.cited
                      ? "bg-indigo-600 text-white"
                      : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                  }`}
                >
                  {passage.cited ? t.evidence.cited : t.evidence.notCited}
                </span>
              </div>

              <div className="mt-2 flex items-center gap-2 text-xs text-zinc-500">
                <span className="w-28 shrink-0">{t.evidence.score}</span>
                <div
                  className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
                  aria-hidden="true"
                >
                  <div
                    className="h-full rounded-full bg-indigo-500"
                    style={{ width: `${Math.round(widths[index] * 100)}%` }}
                  />
                </div>
                <span className="w-12 text-right font-mono">{passage.score.toFixed(3)}</span>
              </div>

              {passage.section && (
                <p className="mt-1 text-xs text-zinc-500">{passage.section}</p>
              )}

              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                  {t.evidence.showContent}
                </summary>
                {/* Repository content is untrusted: rendered as text, never as HTML. */}
                <pre className="mt-1 max-h-64 overflow-auto rounded bg-zinc-950 p-2 font-mono text-xs text-zinc-100">
                  {passage.content}
                </pre>
              </details>
            </li>
          ))}
        </ol>
      </div>
    </details>
  );
}
