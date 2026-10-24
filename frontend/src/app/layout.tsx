import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { LanguageProvider } from "@/i18n/language";
import { DEFAULT_LANGUAGE } from "@/i18n/messages";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Universal AI Workspace",
  description:
    "Questions sur le code d'un dépôt GitHub, avec des réponses qui citent les lignes exactes.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // LanguageProvider updates `lang` when the visitor picks another language.
    <html
      lang={DEFAULT_LANGUAGE}
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <LanguageProvider>{children}</LanguageProvider>
      </body>
    </html>
  );
}
