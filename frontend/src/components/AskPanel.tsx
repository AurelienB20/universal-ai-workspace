"use client";

import { useEffect, useState } from "react";

import { errorMessage } from "@/i18n/errors";
import { useLanguage } from "@/i18n/language";
import { ask } from "@/lib/api";
import type { Answer } from "@/lib/types";

import { AnswerView } from "./AnswerView";

const MAX_QUESTION_CHARS = 2000; // same limit as the backend

interface Exchange {
  id: number;
  question: string;
  answer?: Answer;
  // The error, kept untranslated so that it follows a language change.
  error?: unknown;
}

export function AskPanel({ repository }: { repository: string }) {
  const { t } = useLanguage();
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [pending, setPending] = useState<Exchange | null>(null);

  async function submit() {
    const text = question.trim();
    if (!text || pending) return;
    const exchange: Exchange = { id: Date.now(), question: text };
    setPending(exchange);
    let done: Exchange;
    try {
      done = { ...exchange, answer: await ask(repository, text) };
      setQuestion("");
    } catch (caught) {
      done = { ...exchange, error: caught };
    }
    setPending(null);
    setExchanges((previous) => [done, ...previous]); // newest first
  }

  return (
    <section className="card">
      <h2 className="card-title">{t.askHeading(repository)}</h2>

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
        {pending && <PendingExchange question={pending.question} />}
        {exchanges.map((exchange) => (
          <article key={exchange.id} className="exchange">
            <p className="question">{exchange.question}</p>
            {exchange.answer ? (
              <AnswerView answer={exchange.answer} />
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

function PendingExchange({ question }: { question: string }) {
  const { t } = useLanguage();
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <article className="exchange" aria-busy="true">
      <p className="question">{question}</p>
      <p className="animate-pulse text-sm text-zinc-500" aria-live="polite">
        {t.thinking(seconds)}
      </p>
    </article>
  );
}
