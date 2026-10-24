// Interface texts. French is the reference: the English dictionary must have exactly
// the same keys and signatures (checked by the `Messages` type).

import type { JobStage } from "@/lib/types";

const fr = {
  languageName: "Français",
  languageLabel: "Langue",
  tagline:
    "Importez un dépôt GitHub public, puis posez vos questions sur son code. Chaque réponse cite les lignes exactes.",
  sourceCode: "Code source",

  repoHeading: "1. Dépôt",
  repoLabel: "URL du dépôt GitHub",
  importButton: "Importer",
  importing: "Import en cours…",
  changeRepo: "Changer de dépôt",
  stages: {
    queued: "En attente",
    fetching: "Téléchargement du dépôt",
    chunking: "Découpage des fichiers",
    embedding: "Calcul des embeddings",
    done: "Terminé",
  } satisfies Record<JobStage | "queued", string>,
  embeddedProgress: (done: number, total: number) => `${done} / ${total} passages`,
  importSummary: (files: number, chunks: number) =>
    `${files} fichiers indexés, ${chunks} passages`,
  reusedIndex: "index existant réutilisé",
  importFailed: (error: string) => `L'import a échoué : ${error}`,

  askHeading: (repository: string) => `2. Questions sur ${repository}`,
  questionLabel: "Votre question",
  questionPlaceholder: "Ex. : Comment les signatures sont-elles vérifiées ?",
  askButton: "Demander",
  askHint: "Ctrl + Entrée pour envoyer",
  thinking: (seconds: number) => `Recherche et rédaction de la réponse… ${seconds} s`,
  sources: "Sources",
  insufficientContext:
    "Contexte insuffisant : les passages trouvés ne permettent pas de répondre complètement.",
  answeredBy: (model: string, commit: string) => `${model} · commit ${commit}`,

  errors: {
    network: "Impossible de joindre le serveur de l'interface.",
    unauthorized: "Le serveur de l'interface n'a pas la bonne clé d'API (API_KEY).",
    invalidUrl:
      "URL invalide : indiquez l'URL d'un dépôt GitHub public, par exemple https://github.com/pallets/itsdangerous.",
    notIndexed: "Ce dépôt n'est pas (ou plus) indexé : importez-le à nouveau.",
    reimport: "Ce dépôt doit être réimporté (le modèle d'embeddings a changé).",
    refused: "La question n'a pas pu être traitée.",
    tooLarge: "Requête trop volumineuse.",
    tooMany: (wait: string | null) =>
      `Trop de requêtes, ou budget quotidien atteint.${wait ? ` Réessayez dans ${wait}.` : ""}`,
    backendDown: "Le backend est injoignable.",
    unavailable: "Service indisponible : clé de fournisseur manquante, ou fournisseur en panne.",
    unexpected: (status: number) => `Erreur inattendue (HTTP ${status}).`,
  },
  duration: (seconds: number) =>
    seconds < 60
      ? `${seconds} s`
      : seconds < 3600
        ? `${Math.ceil(seconds / 60)} min`
        : `${Math.ceil(seconds / 3600)} h`,
};

export type Messages = typeof fr;

const en: Messages = {
  languageName: "English",
  languageLabel: "Language",
  tagline:
    "Import a public GitHub repository, then ask questions about its code. Every answer cites the exact lines.",
  sourceCode: "Source code",

  repoHeading: "1. Repository",
  repoLabel: "GitHub repository URL",
  importButton: "Import",
  importing: "Importing…",
  changeRepo: "Change repository",
  stages: {
    queued: "Queued",
    fetching: "Downloading the repository",
    chunking: "Splitting files",
    embedding: "Computing embeddings",
    done: "Done",
  },
  embeddedProgress: (done, total) => `${done} / ${total} passages`,
  importSummary: (files, chunks) => `${files} files indexed, ${chunks} passages`,
  reusedIndex: "existing index reused",
  importFailed: (error) => `The import failed: ${error}`,

  askHeading: (repository) => `2. Questions about ${repository}`,
  questionLabel: "Your question",
  questionPlaceholder: "E.g. How are signatures verified?",
  askButton: "Ask",
  askHint: "Ctrl + Enter to send",
  thinking: (seconds) => `Searching and writing the answer… ${seconds} s`,
  sources: "Sources",
  insufficientContext:
    "Insufficient context: the passages found do not fully answer the question.",
  answeredBy: (model, commit) => `${model} · commit ${commit}`,

  errors: {
    network: "Cannot reach the interface server.",
    unauthorized: "The interface server does not have the right API key (API_KEY).",
    invalidUrl:
      "Invalid URL: enter the URL of a public GitHub repository, for example https://github.com/pallets/itsdangerous.",
    notIndexed: "This repository is not (or no longer) indexed: import it again.",
    reimport: "This repository must be imported again (the embedding model changed).",
    refused: "The question could not be processed.",
    tooLarge: "Request too large.",
    tooMany: (wait) => `Too many requests, or daily budget reached.${wait ? ` Try again in ${wait}.` : ""}`,
    backendDown: "The backend is unreachable.",
    unavailable: "Service unavailable: a provider key is missing, or a provider is down.",
    unexpected: (status) => `Unexpected error (HTTP ${status}).`,
  },
  duration: (seconds) =>
    seconds < 60
      ? `${seconds} s`
      : seconds < 3600
        ? `${Math.ceil(seconds / 60)} min`
        : `${Math.ceil(seconds / 3600)} h`,
};

export const LANGUAGES = ["fr", "en"] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = "fr";

export const messages: Record<Language, Messages> = { fr, en };
