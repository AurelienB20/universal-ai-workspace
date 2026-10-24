// Content of the "How it is built" page (/architecture). French is the reference:
// the English version must have the same structure (checked by a test). Code paths
// do not depend on the language, so they live in STEP_CODE and DECISION_CODE.

import type { Language } from "./messages";

export const REPOSITORY_URL = "https://github.com/AurelienB20/universal-ai-workspace";

export function codeUrl(path: string): string {
  return `${REPOSITORY_URL}/blob/main/${path}`;
}

export type StepId =
  | "import"
  | "read"
  | "chunk"
  | "embed"
  | "search"
  | "generate"
  | "cite";

export const STEP_IDS: StepId[] = ["import", "read", "chunk", "embed", "search", "generate", "cite"];

export const STEP_CODE: Record<StepId, string[]> = {
  import: [
    "backend/src/uaw/connectors/github/client.py",
    "backend/src/uaw/connectors/github/url.py",
  ],
  read: [
    "backend/src/uaw/connectors/github/archive.py",
    "backend/src/uaw/connectors/github/filters.py",
  ],
  chunk: ["backend/src/uaw/chunking/lines.py", "backend/src/uaw/chunking/markdown.py"],
  embed: ["backend/src/uaw/embeddings/voyage.py", "backend/src/uaw/ingestion/pipeline.py"],
  search: ["backend/src/uaw/storage/search.py", "backend/src/uaw/retrieval/retriever.py"],
  generate: [
    "backend/src/uaw/generation/prompt.py",
    "backend/src/uaw/generation/claude.py",
    "backend/src/uaw/generation/json_stream.py",
  ],
  cite: ["backend/src/uaw/generation/citations.py", "backend/tests/unit/test_citations.py"],
};

interface Step {
  title: string;
  // One line, shown on the step button.
  short: string;
  what: string[];
  choice: string;
  alternatives: { name: string; why: string }[];
  // A real figure for this step.
  figure: string;
}

interface Decision {
  title: string;
  decision: string;
  why: string;
  tradeoff: string;
  revisit: string;
  code: string;
}

export interface ArchitectureContent {
  nav: { demo: string; architecture: string };
  hero: { eyebrow: string; title: string; intro: string; tryDemo: string; sourceCode: string };
  pipeline: {
    heading: string;
    intro: string;
    labels: {
      what: string;
      choice: string;
      alternatives: string;
      figure: string;
      code: string;
      step: (index: number, total: number) => string;
    };
    steps: Record<StepId, Step>;
  };
  diagram: {
    heading: string;
    intro: string;
    title: string;
    nodes: {
      browser: string;
      web: string;
      webNote: string;
      api: string;
      apiNote: string;
      db: string;
      dbNote: string;
      voyage: string;
      claude: string;
      github: string;
    };
    zones: { untrusted: string; server: string; providers: string };
    flows: { archive: string; embeddings: string; answer: string; vectors: string };
    legend: { key: string; untrusted: string };
  };
  decisions: {
    heading: string;
    intro: string;
    labels: { why: string; tradeoff: string; revisit: string; code: string };
    items: Decision[];
  };
  safeguards: { heading: string; intro: string; items: { title: string; text: string }[] };
  metrics: {
    heading: string;
    intro: string;
    rows: { label: string; value: string }[];
    caveat: string;
  };
}

const fr: ArchitectureContent = {
  nav: { demo: "Démo", architecture: "Comment c'est construit" },
  hero: {
    eyebrow: "Comment c'est construit",
    title: "Un RAG de bout en bout, où chaque citation est vérifiée par le code",
    intro:
      "Du téléchargement d'un dépôt GitHub jusqu'à la réponse citée, voici chaque étape, le choix fait à chaque fois, les alternatives écartées et le compromis assumé. Chaque affirmation renvoie au code qui la met en œuvre.",
    tryDemo: "Essayer la démo",
    sourceCode: "Code source",
  },
  pipeline: {
    heading: "Le pipeline, étape par étape",
    intro:
      "Les quatre premières étapes ont lieu une fois, à l'import. Les trois dernières, à chaque question. Cliquez sur une étape.",
    labels: {
      what: "Ce qui se passe",
      choice: "Le choix",
      alternatives: "Alternatives écartées",
      figure: "En chiffres",
      code: "Le code",
      step: (index, total) => `Étape ${index} sur ${total}`,
    },
    steps: {
      import: {
        title: "Import depuis GitHub",
        short: "Un commit figé, une seule archive",
        what: [
          "L'URL est validée strictement : uniquement https://github.com/propriétaire/dépôt, sans port, sans identifiants, sans chemin en plus.",
          "Le dépôt est figé sur le dernier commit de sa branche par défaut : toutes les citations pointeront vers ce commit exact.",
          "L'archive est téléchargée en flux, avec une taille maximale et un délai global ; les redirections ne vont que vers des hôtes autorisés.",
        ],
        choice:
          "Télécharger l'archive tar.gz du commit, en une requête, plutôt que cloner ou lire les fichiers un par un.",
        alternatives: [
          {
            name: "git clone",
            why: "Demande un binaire git sur le serveur et apporte tout l'historique, inutile ici.",
          },
          {
            name: "Un appel d'API par fichier",
            why: "Des milliers de requêtes : la limite de 60 requêtes par heure sans jeton serait atteinte tout de suite.",
          },
        ],
        figure: "Dépôts jusqu'à 200 Mo, archive jusqu'à 50 Mo, au plus 3 000 fichiers indexés.",
      },
      read: {
        title: "Lecture sécurisée",
        short: "Le dépôt est une entrée non fiable",
        what: [
          "L'archive est lue en mémoire, jamais extraite sur le disque, et rien n'y est exécuté.",
          "Les bombes de décompression, les chemins dangereux (« ../ », liens) et les fichiers trop gros sont refusés.",
          "Les dépendances, le code compilé, les fichiers de verrouillage, minifiés, binaires ou sensibles sont ignorés, avec la raison pour chacun.",
        ],
        choice:
          "Traiter le dépôt comme une entrée hostile : lecture en mémoire avec des limites strictes, plutôt qu'extraction puis parcours.",
        alternatives: [
          {
            name: "Extraire sur le disque",
            why: "Expose aux attaques par chemin (« zip slip ») et peut remplir le disque du serveur.",
          },
          {
            name: "Tout indexer",
            why: "Des node_modules ou des fichiers .env noieraient la recherche, et pourraient exposer des secrets.",
          },
        ],
        figure: "Au plus 300 Mo décompressés, 50 000 entrées, 256 Ko par fichier.",
      },
      chunk: {
        title: "Découpage en passages",
        short: "Des plages de lignes exactes",
        what: [
          "Chaque fichier est découpé en passages d'environ 2 000 caractères au plus, chacun étant exactement les lignes N à M du fichier.",
          "Le code est coupé aux définitions de premier niveau (avec leurs décorateurs et commentaires), puis entre les méthodes, puis aux lignes vides.",
          "Le Markdown est découpé par titre ; chaque passage garde son fil d'Ariane (« Installation > Windows »).",
        ],
        choice:
          "Un découpage par lignes, guidé par des frontières détectées, plutôt qu'en fenêtres de tokens.",
        alternatives: [
          {
            name: "Fenêtres de taille fixe",
            why: "Coupent au milieu d'une fonction, et une citation ne correspondrait plus à des lignes exactes.",
          },
          {
            name: "Un analyseur syntaxique par langage",
            why: "Une dépendance par langage, pour un gain faible : les frontières de premier niveau suffisent.",
          },
        ],
        figure: "pallets/itsdangerous : 41 fichiers deviennent 99 passages.",
      },
      embed: {
        title: "Embeddings",
        short: "Un modèle spécialisé pour le code",
        what: [
          "Chaque passage devient un vecteur de 1 024 dimensions, avec le modèle voyage-code-3.",
          "Le texte vectorisé commence par le chemin du fichier (et la section Markdown) ; le contenu stocké reste brut.",
          "Les lots respectent les limites de l'API ; les erreurs temporaires sont réessayées avec un délai croissant ; chaque réponse est validée.",
        ],
        choice:
          "voyage-code-3, entraîné sur du code, avec des types d'entrée distincts pour les documents et les questions.",
        alternatives: [
          {
            name: "Un modèle d'embeddings généraliste",
            why: "Moins bon sur le code et ses identifiants.",
          },
          {
            name: "Un modèle local",
            why: "Trop lourd pour un petit serveur, et nettement moins bon sur le code.",
          },
        ],
        figure:
          "Le snapshot ne devient interrogeable qu'une fois chaque passage vectorisé ; réimporter le même commit ne coûte rien.",
      },
      search: {
        title: "Recherche",
        short: "Les 8 passages les plus pertinents",
        what: [
          "La question est vectorisée, puis comparée aux passages du dernier snapshot prêt du dépôt (distance cosinus).",
          "Un index HNSW couvre tous les dépôts : pgvector continue son parcours jusqu'à trouver assez de passages du bon dépôt.",
          "Un dépôt vectorisé avec un autre modèle est refusé, au lieu de comparer des vecteurs incompatibles.",
          "Les 30 meilleurs passages sont relus par un modèle de reclassement (Voyage rerank-3), qui lit la question et chaque passage ensemble ; les fichiers de test sont classés plus bas, sauf si la question parle de tests.",
        ],
        choice:
          "PostgreSQL + pgvector : les vecteurs et les métadonnées dans la même base transactionnelle.",
        alternatives: [
          {
            name: "Une base vectorielle dédiée",
            why: "Un service de plus à exploiter, et plus de transaction commune avec les métadonnées.",
          },
          {
            name: "Une recherche filtrée naïve",
            why: "Garde les voisins de toute la table puis les filtre tous : un test montre qu'elle perd chaque résultat.",
          },
        ],
        figure: "Environ 0,6 s par recherche, embedding et reclassement compris.",
      },
      generate: {
        title: "Génération",
        short: "Claude, avec une sortie structurée",
        what: [
          "Les passages sont donnés au modèle sous des identifiants opaques (S1, S2…), échappés dans des balises <source> : un fichier ne peut pas en fermer une, ni en forger une autre.",
          "Les consignes disent que les passages sont des données, jamais des ordres : des tests d'injection de prompt le vérifient contre le vrai modèle.",
          "Un schéma JSON impose {answer, insufficient_context} : le modèle peut dire que le contexte ne suffit pas au lieu d'inventer.",
          "La réponse arrive en streaming : les passages d'abord, puis le texte au fil de l'écriture, lu dans le JSON incomplet. Ce brouillon est remplacé par la réponse vérifiée.",
        ],
        choice:
          "Le SDK Anthropic directement, avec une sortie structurée et un effort de réflexion fixé explicitement.",
        alternatives: [
          {
            name: "Un framework RAG (LangChain…)",
            why: "Cache le prompt et la structure exacte, et ajoute beaucoup de dépendances pour un pipeline de trois appels.",
          },
          {
            name: "Une réponse en texte libre",
            why: "Plus rien ne distingue une vraie réponse d'un aveu d'ignorance, ni une réponse tronquée.",
          },
        ],
        figure:
          "Passages affichés après 0,6 s, réponse complète en 8 s environ ; 4 000 tokens en entrée, 700 en sortie, environ 0,03 $ par question.",
      },
      cite: {
        title: "Vérification des citations",
        short: "Le modèle ne peut rien inventer",
        what: [
          "Le serveur relit chaque [Sn] de la réponse et le remplace par le fichier, les lignes et un lien GitHub vers le commit indexé.",
          "Un identifiant qui n'a pas été fourni au modèle est supprimé de la réponse, et signalé dans la trace.",
          "Le résultat : un nom de fichier ou un numéro de ligne inventé ne peut pas apparaître dans une citation.",
        ],
        choice:
          "Des identifiants opaques résolus par le serveur, plutôt que de demander au modèle d'écrire lui-même fichier et lignes.",
        alternatives: [
          {
            name: "Le modèle écrit « fichier:ligne »",
            why: "Les LLM inventent des chemins et des numéros de ligne plausibles : seule une vérification serait possible, pas une garantie.",
          },
        ],
        figure: "Garanti par le code et vérifié par des tests, pas seulement demandé dans le prompt.",
      },
    },
  },
  diagram: {
    heading: "L'architecture",
    intro:
      "Le navigateur ne parle qu'au serveur Next.js, qui détient la clé d'API. L'API et la base ne sont jamais exposées à Internet.",
    title: "Schéma d'architecture",
    nodes: {
      browser: "Navigateur",
      web: "Next.js",
      webNote: "clé d'API, CSP",
      api: "FastAPI",
      apiNote: "rôles, limites, budgets",
      db: "PostgreSQL",
      dbNote: "pgvector, HNSW",
      voyage: "Voyage",
      claude: "Claude",
      github: "GitHub",
    },
    zones: {
      untrusted: "Non fiable",
      server: "Serveur (privé)",
      providers: "Fournisseurs externes",
    },
    flows: {
      archive: "archive du commit",
      embeddings: "embeddings",
      answer: "réponse",
      vectors: "SQL + vecteurs",
    },
    legend: {
      key: "La clé d'API ne quitte jamais le serveur",
      untrusted: "Contenu non fiable (visiteurs, dépôts)",
    },
  },
  decisions: {
    heading: "Les décisions d'architecture",
    intro:
      "Chaque choix a un coût. Voici ce qui a été décidé, pourquoi, ce qui a été accepté en échange, et ce qui ferait changer d'avis.",
    labels: {
      why: "Pourquoi",
      tradeoff: "Compromis accepté",
      revisit: "À revoir si",
      code: "Voir le code",
    },
    items: [
      {
        title: "Le serveur résout les citations",
        decision: "Le modèle cite des identifiants opaques ; le serveur les traduit en fichiers et lignes.",
        why: "C'est la seule façon de garantir, et pas seulement d'espérer, qu'aucune source n'est inventée.",
        tradeoff: "Le modèle ne peut citer qu'un passage entier, pas une ligne précise à l'intérieur.",
        revisit: "Des citations plus fines deviennent nécessaires : découper les passages plus petit.",
        code: "backend/src/uaw/generation/citations.py",
      },
      {
        title: "pgvector plutôt qu'une base vectorielle",
        decision: "Vecteurs, passages, snapshots et consommation vivent dans le même PostgreSQL.",
        why: "Un seul service à exploiter et à sauvegarder, des transactions et des contraintes d'intégrité réelles.",
        tradeoff: "Moins de fonctions avancées qu'une base dédiée ; le filtrage exige les parcours itératifs.",
        revisit: "Des dizaines de millions de vecteurs, ou un besoin de recherche multi-tenant à grande échelle.",
        code: "backend/src/uaw/storage/search.py",
      },
      {
        title: "Des snapshots figés sur un commit",
        decision: "Chaque import crée un snapshot immuable, interrogeable seulement une fois complet.",
        why: "Une citation pointe toujours vers les lignes qui ont vraiment été lues, même après des commits.",
        tradeoff: "Le dépôt n'est pas à jour tant qu'on ne le réimporte pas.",
        revisit: "Il faut suivre un dépôt en continu : import incrémental déclenché par webhook.",
        code: "backend/src/uaw/ingestion/pipeline.py",
      },
      {
        title: "Un budget par réservation",
        decision: "Chaque question réserve son coût au pire avant de démarrer, sous un verrou PostgreSQL.",
        why: "« Vérifier puis agir » laisse 20 questions simultanées dépasser le budget ensemble.",
        tradeoff: "Le budget est sous-utilisé de la marge de sécurité de chaque réservation.",
        revisit: "Plusieurs instances : le verrou tient déjà, il suffit que toutes partagent la base.",
        code: "backend/src/uaw/usage/tracker.py",
      },
      {
        title: "Pas de Redis ni de file de tâches (pour l'instant)",
        decision: "Les imports tournent dans le processus de l'API, avec une limite de concurrence ; les limites de requêtes sont en mémoire.",
        why: "Pour une démo sur un petit serveur, deux services de moins à exploiter, sans perte réelle.",
        tradeoff: "Un seul processus d'API ; un redémarrage interrompt les imports en cours (signalés comme échoués).",
        revisit: "Plusieurs instances, ou des imports longs et nombreux : file de tâches et compteurs partagés.",
        code: "backend/src/uaw/ingestion/runner.py",
      },
      {
        title: "Next.js comme intermédiaire",
        decision: "Le navigateur appelle le serveur Next.js, qui ajoute la clé et relaie vers l'API.",
        why: "La clé ne quitte jamais le serveur, et l'API n'est pas exposée : pas de CORS à configurer.",
        tradeoff: "Un saut réseau de plus, et des routes de relais à maintenir.",
        revisit: "Des comptes utilisateurs : sessions côté serveur, avec la même architecture.",
        code: "frontend/src/lib/backend.ts",
      },
      {
        title: "Des réponses en cache, dites comme telles",
        decision: "Les questions suggérées sont répondues une fois, puis servies depuis un cache, avec leur date de génération affichée.",
        why: "Une démo instantanée et gratuite pour le visiteur, sans faire passer une réponse ancienne pour une réponse en direct.",
        tradeoff: "Les suggestions doivent être régénérées après chaque nouvel import du dépôt.",
        revisit: "Les questions des visiteurs se répètent : un cache sémantique des questions.",
        code: "backend/src/uaw/storage/cached_answers.py",
      },
      {
        title: "Mesurer avant d'optimiser",
        decision: "Un changement de la recherche n'est gardé que s'il améliore l'évaluation sur le jeu dev, puis sur le jeu test mis de côté.",
        why: "Sans mesure, une technique à la mode peut dégrader la qualité sans qu'on le voie. La recherche hybride faisait moins bien : elle reste désactivée. Classer les tests plus bas a fait passer le MRR de Flask de 0,71 à 0,81. Le reclassement semblait à égalité sur le jeu dev ; une règle fixée avant de lancer le jeu test a tranché : 0,76 → 0,91, il est activé (0,90 sur toutes les questions).",
        tradeoff: "Annoter des questions à la ligne près prend du temps, et une étiquette oubliée fait paraître la recherche moins bonne : les échecs sont relus un par un.",
        revisit: "Jamais : c'est la règle du projet.",
        code: "backend/src/uaw/evaluation/metrics.py",
      },
    ],
  },
  safeguards: {
    heading: "Sécurité et coûts",
    intro: "Une démo publique est une cible : coût, abus et contenu hostile. Chaque garde-fou est testé.",
    items: [
      {
        title: "Deux rôles",
        text: "La clé de démo ne peut qu'interroger une liste blanche de dépôts. Un dépôt hors liste reçoit la même 404 qu'un dépôt inconnu.",
      },
      {
        title: "Budgets journaliers",
        text: "Obligatoires en production, réservés de façon atomique : des requêtes simultanées ne peuvent pas les dépasser ensemble.",
      },
      {
        title: "Limites",
        text: "Requêtes par visiteur, au plus 4 questions en même temps, taille des requêtes bornée.",
      },
      {
        title: "Contenu hostile",
        text: "Archives lues en mémoire, passages échappés pour le modèle, réponses affichées sans HTML brut, tests d'injection de prompt.",
      },
      {
        title: "En-têtes de sécurité",
        text: "Une Content Security Policy limitée au site lui-même, pas d'affichage dans un cadre, pas de plugins.",
      },
      {
        title: "Traçabilité",
        text: "Chaque requête a un identifiant repris dans tous les logs ; chaque appel de modèle est compté et enregistré.",
      },
    ],
  },
  metrics: {
    heading: "Mesuré, pas supposé",
    intro: "Sur pallets/itsdangerous, avec Claude Opus 5.5 :",
    rows: [
      { label: "Temps de réponse", value: "environ 10 s (7 à 12 s observés)" },
      { label: "Tokens par question", value: "1 800 à 5 800 en entrée, 400 à 900 en sortie" },
      { label: "Coût par question", value: "environ 0,03 $" },
      { label: "Recherche sur Flask, au niveau des lignes", value: "hit@1 0,86 · recall@5 0,92 · MRR 0,90" },
      { label: "Noms exacts / questions en français", value: "MRR 1,00 / 1,00" },
      { label: "Tests", value: "572 backend, 46 frontend, en CI à chaque push" },
    ],
    caveat:
      "65 questions annotées à la ligne près sur deux dépôts, par catégorie, avec un jeu dev pour régler et un jeu test mis de côté. Classer les tests plus bas a corrigé les questions sur un nom exact, le reclassement les questions en français ; les paraphrases (MRR 0,72) et les questions sur plusieurs fichiers (0,75) restent les plus faibles. Chaque changement n'est gardé que s'il fait mieux sur le jeu test.",
  },
};

const en: ArchitectureContent = {
  nav: { demo: "Demo", architecture: "How it is built" },
  hero: {
    eyebrow: "How it is built",
    title: "An end-to-end RAG system where code checks every citation",
    intro:
      "From downloading a GitHub repository to the cited answer: every step, the choice made each time, the alternatives ruled out and the trade-off accepted. Every claim links to the code that implements it.",
    tryDemo: "Try the demo",
    sourceCode: "Source code",
  },
  pipeline: {
    heading: "The pipeline, step by step",
    intro:
      "The first four steps run once, at import time. The last three, for every question. Click a step.",
    labels: {
      what: "What happens",
      choice: "The choice",
      alternatives: "Alternatives ruled out",
      figure: "In numbers",
      code: "The code",
      step: (index, total) => `Step ${index} of ${total}`,
    },
    steps: {
      import: {
        title: "Import from GitHub",
        short: "One pinned commit, one archive",
        what: [
          "The URL is strictly validated: only https://github.com/owner/repository, with no port, credentials or extra path.",
          "The repository is pinned to the latest commit of its default branch: every citation will point to that exact commit.",
          "The archive is streamed with a size cap and an overall timeout; redirects only go to allowlisted hosts.",
        ],
        choice:
          "Download the commit's tar.gz archive in one request, rather than cloning or reading files one by one.",
        alternatives: [
          {
            name: "git clone",
            why: "Needs a git binary on the server and brings the whole history, useless here.",
          },
          {
            name: "One API call per file",
            why: "Thousands of requests: the 60 requests per hour limit without a token would be hit at once.",
          },
        ],
        figure: "Repositories up to 200 MB, archives up to 50 MB, at most 3,000 indexed files.",
      },
      read: {
        title: "Safe reading",
        short: "The repository is untrusted input",
        what: [
          "The archive is read in memory, never extracted to disk, and nothing in it is executed.",
          "Decompression bombs, unsafe paths (\"../\", links) and oversized files are rejected.",
          "Dependencies, build output, lockfiles, minified, binary and sensitive files are skipped, with the reason for each.",
        ],
        choice:
          "Treat the repository as hostile input: read it in memory with strict limits, rather than extracting it and walking the tree.",
        alternatives: [
          {
            name: "Extract to disk",
            why: "Exposed to path attacks (\"zip slip\"), and can fill the server's disk.",
          },
          {
            name: "Index everything",
            why: "node_modules or .env files would drown the search, and could expose secrets.",
          },
        ],
        figure: "At most 300 MB uncompressed, 50,000 entries, 256 KB per file.",
      },
      chunk: {
        title: "Chunking",
        short: "Exact line ranges",
        what: [
          "Each file is split into passages of at most about 2,000 characters, each being exactly lines N to M of the file.",
          "Code is cut at top-level definitions (with their decorators and comments), then between methods, then at blank lines.",
          "Markdown is split by heading; each passage keeps its breadcrumb (\"Install > Windows\").",
        ],
        choice: "Line-based chunking guided by detected boundaries, rather than token windows.",
        alternatives: [
          {
            name: "Fixed-size windows",
            why: "They cut through functions, and a citation would no longer match exact lines.",
          },
          {
            name: "A parser per language",
            why: "One dependency per language for little gain: top-level boundaries are enough.",
          },
        ],
        figure: "pallets/itsdangerous: 41 files become 99 passages.",
      },
      embed: {
        title: "Embeddings",
        short: "A model trained for code",
        what: [
          "Each passage becomes a 1,024-dimension vector, with the voyage-code-3 model.",
          "The embedded text starts with the file path (and Markdown section); the stored content stays raw.",
          "Batches stay within the API limits; transient errors are retried with growing delays; every response is validated.",
        ],
        choice:
          "voyage-code-3, trained on code, with distinct input types for documents and questions.",
        alternatives: [
          {
            name: "A general-purpose embedding model",
            why: "Weaker on code and its identifiers.",
          },
          {
            name: "A local model",
            why: "Too heavy for a small server, and clearly weaker on code.",
          },
        ],
        figure:
          "A snapshot becomes searchable only once every passage has its vector; re-importing the same commit costs nothing.",
      },
      search: {
        title: "Search",
        short: "The 8 most relevant passages",
        what: [
          "The question is embedded, then compared with the passages of the repository's latest ready snapshot (cosine distance).",
          "One HNSW index covers every repository: pgvector keeps scanning until it finds enough passages of the right one.",
          "A repository embedded with another model is refused, instead of comparing incompatible vectors.",
          "The 30 best passages are read again by a reranking model (Voyage rerank-3), which reads the question and each passage together; test files rank lower, unless the question is about tests.",
        ],
        choice: "PostgreSQL + pgvector: vectors and metadata in the same transactional database.",
        alternatives: [
          {
            name: "A dedicated vector database",
            why: "One more service to run, and no shared transaction with the metadata.",
          },
          {
            name: "A naive filtered search",
            why: "Keeps the neighbours of the whole table, then filters them all out: a test shows it losing every result.",
          },
        ],
        figure: "About 0.6 s per search, embedding and reranking included.",
      },
      generate: {
        title: "Generation",
        short: "Claude, with structured output",
        what: [
          "Passages reach the model under opaque IDs (S1, S2…), escaped inside <source> tags: a file cannot close one, nor forge another.",
          "The instructions say passages are data, never commands: prompt-injection tests check it against the real model.",
          "A JSON schema enforces {answer, insufficient_context}: the model can say the context is not enough instead of inventing.",
          "The answer is streamed: the passages first, then the text as it is written, read out of the incomplete JSON. This draft is replaced by the checked answer.",
        ],
        choice:
          "The Anthropic SDK directly, with structured output and an explicitly set thinking effort.",
        alternatives: [
          {
            name: "A RAG framework (LangChain…)",
            why: "Hides the exact prompt and structure, and adds many dependencies for a three-call pipeline.",
          },
          {
            name: "A free-text answer",
            why: "Nothing would tell a real answer from an admission of ignorance, or from a truncated one.",
          },
        ],
        figure:
          "Passages shown after 0.6 s, the full answer in about 8 s; 4,000 input and 700 output tokens, about $0.03 per question.",
      },
      cite: {
        title: "Citation check",
        short: "The model cannot invent anything",
        what: [
          "The server reads every [Sn] in the answer and replaces it with the file, the lines and a GitHub link at the indexed commit.",
          "An ID the model was not given is removed from the answer, and reported in the trace.",
          "The result: an invented file name or line number cannot appear in a citation.",
        ],
        choice:
          "Opaque IDs resolved by the server, rather than asking the model to write file and lines itself.",
        alternatives: [
          {
            name: "The model writes \"file:line\"",
            why: "LLMs invent plausible paths and line numbers: only a check would be possible, not a guarantee.",
          },
        ],
        figure: "Guaranteed by code and checked by tests, not merely requested in the prompt.",
      },
    },
  },
  diagram: {
    heading: "The architecture",
    intro:
      "The browser only talks to the Next.js server, which holds the API key. The API and the database are never exposed to the internet.",
    title: "Architecture diagram",
    nodes: {
      browser: "Browser",
      web: "Next.js",
      webNote: "API key, CSP",
      api: "FastAPI",
      apiNote: "roles, limits, budgets",
      db: "PostgreSQL",
      dbNote: "pgvector, HNSW",
      voyage: "Voyage",
      claude: "Claude",
      github: "GitHub",
    },
    zones: {
      untrusted: "Untrusted",
      server: "Server (private)",
      providers: "External providers",
    },
    flows: {
      archive: "commit archive",
      embeddings: "embeddings",
      answer: "answer",
      vectors: "SQL + vectors",
    },
    legend: {
      key: "The API key never leaves the server",
      untrusted: "Untrusted content (visitors, repositories)",
    },
  },
  decisions: {
    heading: "Architecture decisions",
    intro:
      "Every choice has a cost. Here is what was decided, why, what was accepted in exchange, and what would change the decision.",
    labels: {
      why: "Why",
      tradeoff: "Trade-off accepted",
      revisit: "Revisit if",
      code: "See the code",
    },
    items: [
      {
        title: "The server resolves citations",
        decision: "The model cites opaque IDs; the server turns them into files and lines.",
        why: "It is the only way to guarantee, not just hope, that no source is invented.",
        tradeoff: "The model can only cite a whole passage, not one line inside it.",
        revisit: "Finer citations become necessary: split passages smaller.",
        code: "backend/src/uaw/generation/citations.py",
      },
      {
        title: "pgvector rather than a vector database",
        decision: "Vectors, passages, snapshots and usage live in the same PostgreSQL.",
        why: "One service to run and back up, with real transactions and integrity constraints.",
        tradeoff: "Fewer advanced features than a dedicated store; filtering needs iterative scans.",
        revisit: "Tens of millions of vectors, or large-scale multi-tenant search.",
        code: "backend/src/uaw/storage/search.py",
      },
      {
        title: "Snapshots pinned to a commit",
        decision: "Each import creates an immutable snapshot, searchable only once complete.",
        why: "A citation always points to the lines that were really read, even after new commits.",
        tradeoff: "The repository is not up to date until it is imported again.",
        revisit: "A repository must be followed continuously: incremental imports from a webhook.",
        code: "backend/src/uaw/ingestion/pipeline.py",
      },
      {
        title: "Budgets by reservation",
        decision: "Each question reserves its worst-case cost before it starts, under a PostgreSQL lock.",
        why: "\"Check, then act\" lets 20 simultaneous questions overshoot the budget together.",
        tradeoff: "The budget is under-used by each reservation's safety margin.",
        revisit: "Several instances: the lock already holds, as long as they share the database.",
        code: "backend/src/uaw/usage/tracker.py",
      },
      {
        title: "No Redis or task queue (yet)",
        decision: "Imports run in the API process with a concurrency limit; rate limits are in memory.",
        why: "For a demo on a small server, two fewer services to run, with no real loss.",
        tradeoff: "A single API process; a restart interrupts running imports (reported as failed).",
        revisit: "Several instances, or many long imports: a task queue and shared counters.",
        code: "backend/src/uaw/ingestion/runner.py",
      },
      {
        title: "Next.js as the go-between",
        decision: "The browser calls the Next.js server, which adds the key and forwards to the API.",
        why: "The key never leaves the server and the API is not exposed: no CORS to configure.",
        tradeoff: "One more network hop, and forwarding routes to maintain.",
        revisit: "User accounts: server-side sessions, in the same architecture.",
        code: "frontend/src/lib/backend.ts",
      },
      {
        title: "Cached answers, labelled as such",
        decision: "Suggested questions are answered once, then served from a cache, with their generation date shown.",
        why: "An instant, free demo for visitors, without passing off an old answer as a live one.",
        tradeoff: "Suggestions must be generated again after each new import of the repository.",
        revisit: "Visitors' questions repeat: a semantic cache of questions.",
        code: "backend/src/uaw/storage/cached_answers.py",
      },
      {
        title: "Measure before optimising",
        decision: "A retrieval change is kept only if it improves the evaluation on the dev split, then on the held-out test split.",
        why: "Without measurement, a fashionable technique can lower quality unnoticed. Hybrid search did worse: it stays off. Ranking tests lower raised the Flask MRR from 0.71 to 0.81. Reranking looked level on the dev split; a rule fixed before running the test split settled it: 0.76 → 0.91, so it is on (0.90 over all questions).",
        tradeoff: "Labeling questions to the line takes time, and a missing label makes retrieval look worse than it is: misses are read one by one.",
        revisit: "Never: it is the project's rule.",
        code: "backend/src/uaw/evaluation/metrics.py",
      },
    ],
  },
  safeguards: {
    heading: "Security and cost",
    intro: "A public demo is a target: cost, abuse and hostile content. Each safeguard is tested.",
    items: [
      {
        title: "Two roles",
        text: "The demo key can only question an allowlist of repositories. One outside the list gets the same 404 as an unknown one.",
      },
      {
        title: "Daily budgets",
        text: "Required in production, reserved atomically: simultaneous requests cannot overshoot them together.",
      },
      {
        title: "Limits",
        text: "Requests per visitor, at most 4 questions at a time, bounded request size.",
      },
      {
        title: "Hostile content",
        text: "Archives read in memory, passages escaped for the model, answers shown without raw HTML, prompt-injection tests.",
      },
      {
        title: "Security headers",
        text: "A Content Security Policy limited to the site itself, no framing, no plugins.",
      },
      {
        title: "Traceability",
        text: "Each request has an ID carried by every log line; each model call is counted and stored.",
      },
    ],
  },
  metrics: {
    heading: "Measured, not assumed",
    intro: "On pallets/itsdangerous, with Claude Opus 5.5:",
    rows: [
      { label: "Answer time", value: "about 10 s (7 to 12 s observed)" },
      { label: "Tokens per question", value: "1,800 to 5,800 in, 400 to 900 out" },
      { label: "Cost per question", value: "about $0.03" },
      { label: "Retrieval on Flask, at line level", value: "hit@1 0.86 · recall@5 0.92 · MRR 0.90" },
      { label: "Exact names / questions in French", value: "MRR 1.00 / 1.00" },
      { label: "Tests", value: "572 backend, 46 frontend, in CI on every push" },
    ],
    caveat:
      "65 questions labeled to the line over two repositories, by category, with a dev split for tuning and a held-out test split. Ranking tests lower fixed questions about an exact name, reranking the questions in French; paraphrases (MRR 0.72) and multi-file questions (0.75) remain the weakest. Each change is kept only if it does better on the test split.",
  },
};

export const architecture: Record<Language, ArchitectureContent> = { fr, en };
