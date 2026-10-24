"use client";

import { useLanguage } from "@/i18n/language";

import { LanguageSwitch } from "./LanguageSwitch";

const REPOSITORY_URL = "https://github.com/AurelienB20/universal-ai-workspace";

export function Header() {
  const { t } = useLanguage();

  return (
    <header className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Universal AI Workspace</h1>
        <LanguageSwitch />
      </div>
      <p className="text-zinc-600 dark:text-zinc-400">{t.tagline}</p>
      <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer" className="link text-sm">
        {t.sourceCode} ↗
      </a>
    </header>
  );
}
