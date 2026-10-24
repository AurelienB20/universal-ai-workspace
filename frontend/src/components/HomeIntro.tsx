"use client";

import Link from "next/link";

import { useLanguage } from "@/i18n/language";

/** What to do on this page, in three steps, and where to see how it works. */
export function HomeIntro() {
  const { t } = useLanguage();

  return (
    <section className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-5 dark:border-indigo-900 dark:bg-indigo-950/30">
      <h2 className="mb-3 text-lg font-semibold">{t.intro.title}</h2>
      <ol className="flex flex-col gap-2 text-sm sm:flex-row sm:gap-4">
        {t.intro.steps.map((step, index) => (
          <li key={step} className="flex flex-1 gap-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
              {index + 1}
            </span>
            <span className="text-zinc-700 dark:text-zinc-300">{step}</span>
          </li>
        ))}
      </ol>
      <Link href="/architecture" className="link mt-4 inline-block text-sm font-medium">
        {t.intro.architectureLink} →
      </Link>
    </section>
  );
}
