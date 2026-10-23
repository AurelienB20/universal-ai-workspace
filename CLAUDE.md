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
  arrêter seulement ce qui a été démarré pour l'occasion (PostgreSQL, serveur uvicorn).
- Ne jamais supprimer de données : pas de `DROP DATABASE`, ni de `docker compose down -v`,
  `docker volume rm`, `docker system prune --volumes`.
- Ne pas faire `wsl --shutdown` : la distribution Debian peut servir à autre chose.
