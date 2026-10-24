import type { Metadata } from "next";

import { ArchitecturePage } from "@/components/architecture/ArchitecturePage";
import { Header } from "@/components/Header";

export const metadata: Metadata = {
  title: "Comment c'est construit · Universal AI Workspace",
  description:
    "Chaque étape du pipeline RAG, chaque choix d'architecture et son compromis, avec des liens vers le code.",
};

export default function Architecture() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-8 sm:py-12">
      <Header />
      <ArchitecturePage />
    </main>
  );
}
