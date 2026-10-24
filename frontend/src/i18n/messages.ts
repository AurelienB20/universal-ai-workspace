// Interface texts. French is the reference: the English dictionary must have exactly
// the same keys and signatures (checked by the `Messages` type).

import type { JobStage } from "@/lib/types";

const fr = {
  languageName: "Français",
  languageLabel: "Langue",
  tagline:
    "Posez vos questions sur le code d'un dépôt GitHub public. Chaque réponse cite les lignes exactes.",
  sourceCode: "Code source",
  intro: {
    title: "Interrogez le code, vérifiez chaque source",
    steps: [
      "Choisissez un dépôt indexé.",
      "Posez une question en langage naturel, ou cliquez sur une question suggérée.",
      "Cliquez sur une citation [S1] pour voir les lignes exactes, ou ouvrez « Voir comment cette réponse a été construite ».",
    ],
    architectureLink: "Comment c'est construit : chaque étape et chaque choix",
  },

  repoHeading: "1. Dépôt",
  repositoriesLabel: "Dépôts indexés",
  loadingRepositories: "Chargement des dépôts…",
  noRepositories: "Aucun dépôt n'est encore indexé.",
  repositoryMeta: (files: number, commit: string) => `${files} fichiers · commit ${commit}`,
  importHeading: "Importer un autre dépôt",
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
  searching: (seconds: number) => `Recherche des passages… ${seconds} s`,
  writing: (passages: number, seconds: number) =>
    `${passages} passage${passages > 1 ? "s" : ""} trouvé${passages > 1 ? "s" : ""} · rédaction de la réponse… ${seconds} s`,
  draftNotice: "Brouillon en cours d'écriture : le serveur vérifie les citations à la fin.",
  sources: "Sources",
  insufficientContext:
    "Contexte insuffisant : les passages trouvés ne permettent pas de répondre complètement.",
  answeredBy: (model: string, commit: string) => `${model} · commit ${commit}`,
  suggestionsHeading: "Questions suggérées",
  suggestionsHint: "Réponses générées à l'avance : affichage immédiat, sans appel au modèle.",
  cachedAnswer: (date: string) => `Réponse en cache, générée le ${date}`,
  dateLocale: "fr-FR",
  evidence: {
    toggle: "Voir comment cette réponse a été construite",
    intro:
      "Ces passages ont été retrouvés par recherche vectorielle, du plus proche de la question (S1) au moins proche, puis donnés au modèle. Il ne peut citer qu'eux : le serveur vérifie chaque citation.",
    introReranked:
      "Ces passages ont été retrouvés par recherche vectorielle, puis relus par un modèle de reclassement qui les classe du plus pertinent (S1) au moins pertinent, avant d'être donnés au modèle. Il ne peut citer qu'eux : le serveur vérifie chaque citation.",
    summary: (passages: number, cited: number) =>
      `${passages} passages retrouvés, ${cited} cité${cited > 1 ? "s" : ""} dans la réponse`,
    timings: (retrieval: string, generation: string) =>
      `Recherche ${retrieval} · génération ${generation}`,
    tokens: (input: string, output: string) => `${input} tokens en entrée, ${output} en sortie`,
    removed: (ids: string[]) =>
      ids.length > 1
        ? `Citations inventées par le modèle, supprimées par le serveur : ${ids.join(", ")}`
        : `Citation inventée par le modèle, supprimée par le serveur : ${ids[0]}`,
    cited: "cité",
    notCited: "non cité",
    score: "similarité (0 à 1)",
    rerankScore: "pertinence (0 à 1)",
    showContent: "Voir le passage",
  },

  errors: {
    network: "Impossible de joindre le serveur de l'interface.",
    interrupted: "La connexion a été coupée avant la fin de la réponse. Reposez la question.",
    unauthorized: "Le serveur de l'interface n'a pas la bonne clé d'API (API_KEY).",
    forbidden: "Cette action n'est pas disponible sur cette démo.",
    invalidUrl:
      "URL invalide : indiquez l'URL d'un dépôt GitHub public, par exemple https://github.com/pallets/itsdangerous.",
    notIndexed: "Ce dépôt n'est pas (ou plus) indexé : importez-le à nouveau.",
    reimport: "Ce dépôt doit être réimporté (le modèle d'embeddings a changé).",
    refused: "La question n'a pas pu être traitée.",
    tooLarge: "Requête trop volumineuse.",
    tooMany: (wait: string | null) =>
      `Trop de requêtes, ou budget quotidien atteint.${wait ? ` Réessayez dans ${wait}.` : ""}`,
    backendDown: "Le backend est injoignable.",
    busy: (wait: string | null) =>
      `Le serveur répond déjà à d'autres questions.${wait ? ` Réessayez dans ${wait}.` : ""}`,
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
    "Ask questions about the code of a public GitHub repository. Every answer cites the exact lines.",
  sourceCode: "Source code",
  intro: {
    title: "Question the code, check every source",
    steps: [
      "Pick an indexed repository.",
      "Ask a question in plain language, or click a suggested question.",
      "Click a [S1] citation to see the exact lines, or open \"See how this answer was built\".",
    ],
    architectureLink: "How it is built: every step and every choice",
  },

  repoHeading: "1. Repository",
  repositoriesLabel: "Indexed repositories",
  loadingRepositories: "Loading repositories…",
  noRepositories: "No repository is indexed yet.",
  repositoryMeta: (files, commit) => `${files} files · commit ${commit}`,
  importHeading: "Import another repository",
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
  searching: (seconds) => `Searching the passages… ${seconds} s`,
  writing: (passages, seconds) =>
    `${passages} passage${passages === 1 ? "" : "s"} found · writing the answer… ${seconds} s`,
  draftNotice: "Draft being written: the server checks the citations at the end.",
  sources: "Sources",
  insufficientContext:
    "Insufficient context: the passages found do not fully answer the question.",
  answeredBy: (model, commit) => `${model} · commit ${commit}`,
  suggestionsHeading: "Suggested questions",
  suggestionsHint: "Answers generated in advance: shown at once, with no model call.",
  cachedAnswer: (date) => `Cached answer, generated on ${date}`,
  dateLocale: "en-GB",
  evidence: {
    toggle: "See how this answer was built",
    intro:
      "These passages were found by vector search, from the closest to the question (S1) to the least close, then given to the model. It can only cite them: the server checks every citation.",
    introReranked:
      "These passages were found by vector search, then read by a reranking model that orders them from the most relevant (S1) to the least, before being given to the model. It can only cite them: the server checks every citation.",
    summary: (passages, cited) => `${passages} passages retrieved, ${cited} cited in the answer`,
    timings: (retrieval, generation) => `Search ${retrieval} · generation ${generation}`,
    tokens: (input, output) => `${input} input tokens, ${output} output`,
    removed: (ids) =>
      ids.length > 1
        ? `Citations invented by the model, removed by the server: ${ids.join(", ")}`
        : `Citation invented by the model, removed by the server: ${ids[0]}`,
    cited: "cited",
    notCited: "not cited",
    score: "similarity (0 to 1)",
    rerankScore: "relevance (0 to 1)",
    showContent: "Show the passage",
  },

  errors: {
    network: "Cannot reach the interface server.",
    interrupted: "The connection was cut before the answer was complete. Ask again.",
    unauthorized: "The interface server does not have the right API key (API_KEY).",
    forbidden: "This action is not available on this demo.",
    invalidUrl:
      "Invalid URL: enter the URL of a public GitHub repository, for example https://github.com/pallets/itsdangerous.",
    notIndexed: "This repository is not (or no longer) indexed: import it again.",
    reimport: "This repository must be imported again (the embedding model changed).",
    refused: "The question could not be processed.",
    tooLarge: "Request too large.",
    tooMany: (wait) => `Too many requests, or daily budget reached.${wait ? ` Try again in ${wait}.` : ""}`,
    backendDown: "The backend is unreachable.",
    busy: (wait) =>
      `The server is already answering other questions.${wait ? ` Try again in ${wait}.` : ""}`,
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
