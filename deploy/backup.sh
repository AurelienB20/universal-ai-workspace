#!/usr/bin/env bash
# Back up the production database to deploy/backups/uaw-<UTC time>.dump.
#   ./backup.sh                 # then check the printed file
# Run it daily from cron (see docs/deployment.md). Backups older than KEEP_DAYS days
# (default 14) are deleted; copy them off the server as well, or a lost server loses
# its backups too.
set -euo pipefail

cd "$(dirname "$0")"
BACKUP_DIR=${BACKUP_DIR:-./backups}
KEEP_DAYS=${KEEP_DAYS:-14}
COMPOSE=(docker compose -f docker-compose.prod.yml)

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
file="$BACKUP_DIR/uaw-$(date -u +%Y%m%dT%H%M%SZ).dump"

# Custom format: compressed, and restorable table by table. Written to a temporary
# name first, so that an interrupted dump never looks like a complete backup.
"${COMPOSE[@]}" exec -T db pg_dump --username=uaw --dbname=uaw --format=custom > "$file.partial"
# A backup that cannot be read is not a backup: list its contents before keeping it.
"${COMPOSE[@]}" exec -T db pg_restore --list < "$file.partial" > /dev/null
mv "$file.partial" "$file"
chmod 600 "$file"

find "$BACKUP_DIR" -name 'uaw-*.dump' -type f -mtime +"$KEEP_DAYS" -delete
echo "$file"
