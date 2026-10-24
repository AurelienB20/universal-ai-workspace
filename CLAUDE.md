# Universal AI Workspace — consignes pour Claude Code

Échanger en français. Avancer jalon par jalon, attendre la validation de l'utilisateur entre deux jalons.

## Développement local sans Docker

Le PC de développement (Windows, 8 Go de RAM) est saturé par Docker Desktop : **ne pas le lancer
en local**. Docker reste réservé au déploiement (OVHcloud) ; conserver `docker-compose.yml`
et les Dockerfiles.

- Par défaut, travailler sans base : tests unitaires et commandes Python dans `backend`
  (`./.venv/Scripts/python.exe -m pytest` exclut déjà les marqueurs `db` et `live`).
- Quand une base est nécessaire (`-m db`, import réel, `/search`, `/ask`) : PostgreSQL 16 +
  pgvector installés dans la distribution WSL `Debian` (script `scripts/setup-wsl-postgres.sh`),
  joignable sur `127.0.0.1:5432` avec le même `DATABASE_URL` que Docker.
  - Démarrer : `wsl -d Debian -u root -- service postgresql start`
  - Arrêter : `wsl -d Debian -u root -- service postgresql stop`
- Avant de démarrer, vérifier s'il tourne déjà (`... service postgresql status`). À la fin,
  arrêter seulement ce qui a été démarré pour l'occasion (PostgreSQL, serveur uvicorn,
  `next dev`).
- Frontend (`frontend/`, Next.js 16) : `npm run lint`, `npm run typecheck`, `npm test` et
  `npm run build` tournent sans backend. `npm run dev` (~300-500 Mo) seulement pour un essai
  réel, puis l'arrêter. Lire `frontend/AGENTS.md` : cette version de Next.js diffère de ce
  que l'on connaît, sa documentation est dans `frontend/node_modules/next/dist/docs/`.
- Le CI GitHub Actions (`.github/workflows/ci.yml`) teste tout et construit les images
  Docker : c'est lui qui vérifie les Dockerfiles, pas le PC local. `gh` est installé dans
  `C:\Program Files\GitHub CLI\gh.exe` (absent du PATH de Git Bash).
- Ne jamais supprimer de données : pas de `DROP DATABASE`, ni de `docker compose down -v`,
  `docker volume rm`, `docker system prune --volumes`.
- Ne pas faire `wsl --shutdown` : la distribution Debian peut servir à autre chose.
