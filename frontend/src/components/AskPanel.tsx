"use client";

import { useEffect, useRef, useState } from "react";

import { errorMessage } from "@/i18n/errors";
import { useLanguage } from "@/i18n/language";
import { askStream, getSuggestions } from "@/lib/api";
import type { Answer, CachedAnswer, Passage } from "@/lib/types";

import { AnswerMarkdown, AnswerView } from "./AnswerView";

const MAX_QUESTION_CHARS = 2000; // same limit as the backend

interface Exchange {
  id: number;
  question: string;
  answer?: Answer;
  // Generation date of a cached answer (suggested question); absent when live.
  cachedAt?: string;
  // The error, kept untranslated so that it follows a language change.
  error?: unknown;
}

// An answer being written: its passages once found, and the unchecked draft.
interface PendingAnswer {
  id: number;
  question: string;
  passages: Passage[] | null;
  draft: string;
}

export function AskPanel({ repository }: { repository: string }) {
  const { t, language } = useLanguage();
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [pending, setPending] = useState<PendingAnswer | null>(null);
  const [suggestions, setSuggestions] = useState<CachedAnswer[]>([]);
  // Exchange keys: a suggestion can be shown several times.
  const nextId = useRef(0);
  // Leaving the panel stops the answer being written (and billed).
  const inFlight = useRef<AbortController | null>(null);
  useEffect(() => () => inFlight.current?.abort(), []);

  // Suggestions are optional: any failure simply shows none.
  useEffect(() => {
    let cancelled = false;
    getSuggestions(repository, language)
      .then((result) => !cancelled && setSuggestions(result.items))
      .catch(() => !cancelled && setSuggestions([]));
    return () => {
      cancelled = true;
    };
  }, [repository, language]);

  function showCached(item: CachedAnswer) {
    const exchange: Exchange = {
      id: nextId.current++,
      question: item.question,
      answer: item.answer,
      cachedAt: item.generated_at,
    };
    setExchanges((previous) => [exchange, ...previous]);
  }

  async function submit() {
    const text = question.trim();
    if (!text || pending) return;
    const exchange: Exchange = { id: nextId.current++, question: text };
    setPending({ ...exchange, passages: null, draft: "" });
    const controller = new AbortController();
    inFlight.current = controller;
    const update = (change: (answer: PendingAnswer) => PendingAnswer) =>
      setPending((current) => (current?.id === exchange.id ? change(current) : current));
    let done: Exchange;
    try {
      const answer = await askStream(
        repository,
        text,
        {
          onSources: (sources) => update((current) => ({ ...current, passages: sources.passages })),
          onDelta: (delta) => update((current) => ({ ...current, draft: current.draft + delta })),
          onReset: () => update((current) => ({ ...current, draft: "" })),
        },
        controller.signal,
      );
      done = { ...exchange, answer };
      setQuestion("");
    } catch (caught) {
      if (controller.signal.aborted) return; // the panel is gone
      done = { ...exchange, error: caught };
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
    }
    // The checked answer replaces the draft.
    setPending(null);
    setExchanges((previous) => [done, ...previous]); // newest first
  }

  return (
    <section className="card">
      <h2 className="card-title">{t.askHeading(repository)}</h2>

      {suggestions.length > 0 && (
        <div className="mb-4">
          <p className="text-sm font-medium">{t.suggestionsHeading}</p>
          <p className="mb-2 text-xs text-zinc-500">{t.suggestionsHint}</p>
          <ul className="flex flex-wrap gap-2">
            {suggestions.map((item) => (
              <li key={item.question}>
                <button
                  type="button"
                  onClick={() => showCached(item)}
                  className="rounded-full border border-zinc-300 px-3 py-1 text-left text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  {item.question}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-2"
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{t.questionLabel}</span>
          <textarea
            rows={3}
            required
            maxLength={MAX_QUESTION_CHARS}
            value={question}
            disabled={pending !== null}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder={t.questionPlaceholder}
            className="input resize-y"
          />
        </label>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-zinc-500">{t.askHint}</span>
          <button type="submit" disabled={pending !== null} className="button-primary">
            {t.askButton}
          </button>
        </div>
      </form>

      <div className="mt-4 flex flex-col gap-4">
        {pending && <PendingExchange answer={pending} />}
        {exchanges.map((exchange) => (
          <article key={exchange.id} className="exchange">
            <p className="question">{exchange.question}</p>
            {exchange.answer ? (
              <AnswerView answer={exchange.answer} cachedAt={exchange.cachedAt} />
            ) : (
              <p role="alert" className="error">
                {errorMessage(exchange.error, t, "ask")}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function PendingExchange({ answer }: { answer: PendingAnswer }) {
  const { t } = useLanguage();
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <article className="exchange" aria-busy="true">
      <p className="question">{answer.question}</p>
      <p className="animate-pulse text-sm text-zinc-500" aria-live="polite">
        {answer.passages === null
          ? t.searching(seconds)
          : t.writing(answer.passages.length, seconds)}
      </p>
      {answer.draft && answer.passages && (
        <div className="flex flex-col gap-2">
          <AnswerMarkdown markdown={answer.draft} citations={answer.passages} />
          <p className="text-xs text-zinc-500">{t.draftNotice}</p>
        </div>
      )}
    </article>
  );
}
