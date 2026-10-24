"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { REPOSITORY_URL, architecture } from "@/i18n/architecture";
import { useLanguage } from "@/i18n/language";

import { LanguageSwitch } from "./LanguageSwitch";

export function Header() {
  const { t, language } = useLanguage();
  const pathname = usePathname();
  const nav = architecture[language].nav;
  const links = [
    { href: "/", label: nav.demo },
    { href: "/architecture", label: nav.architecture },
  ];

  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <Link href="/" className="text-2xl font-semibold tracking-tight">
          Universal AI Workspace
        </Link>
        <div className="flex items-center gap-3">
          <nav className="flex gap-1 text-sm">
            {links.map((link) => {
              const current = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={current ? "page" : undefined}
                  className={`rounded-md px-2.5 py-1 font-medium ${
                    current
                      ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800/60"
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <LanguageSwitch />
        </div>
      </div>
      {pathname === "/" && (
        <>
          <p className="text-zinc-600 dark:text-zinc-400">{t.tagline}</p>
          <a
            href={REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="link text-sm"
          >
            {t.sourceCode} ↗
          </a>
        </>
      )}
    </header>
  );
}
