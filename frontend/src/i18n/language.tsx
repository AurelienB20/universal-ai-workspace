"use client";

// Current language, remembered in the browser (localStorage). The server always
// renders the default language; the browser switches after hydration if needed.

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

import { DEFAULT_LANGUAGE, LANGUAGES, type Language, type Messages, messages } from "./messages";

const STORAGE_KEY = "uaw.language";
const listeners = new Set<() => void>();

function readLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return LANGUAGES.find((language) => language === stored) ?? DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE; // storage blocked (private mode, policies)
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener); // other tabs
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

interface LanguageContextValue {
  language: Language;
  t: Messages;
  setLanguage: (language: Language) => void;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const language = useSyncExternalStore(subscribe, readLanguage, () => DEFAULT_LANGUAGE);

  const setLanguage = useCallback((next: Language) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      return; // storage blocked: the default language stays
    }
    listeners.forEach((listener) => listener());
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <LanguageContext value={{ language, t: messages[language], setLanguage }}>
      {children}
    </LanguageContext>
  );
}

export function useLanguage(): LanguageContextValue {
  const value = useContext(LanguageContext);
  if (value === null) throw new Error("useLanguage() needs a <LanguageProvider>");
  return value;
}
