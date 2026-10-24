"use client";

import { useLanguage } from "@/i18n/language";
import { LANGUAGES, messages } from "@/i18n/messages";

export function LanguageSwitch() {
  const { language, setLanguage, t } = useLanguage();

  return (
    <div role="group" aria-label={t.languageLabel} className="flex gap-1 text-xs">
      {LANGUAGES.map((option) => (
        <button
          key={option}
          type="button"
          lang={option}
          aria-pressed={option === language}
          title={messages[option].languageName}
          onClick={() => setLanguage(option)}
          className={`rounded px-2 py-1 font-semibold uppercase ${
            option === language
              ? "bg-indigo-600 text-white"
              : "text-zinc-600 hover:bg-zinc-200 dark:text-zinc-400 dark:hover:bg-zinc-800"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
