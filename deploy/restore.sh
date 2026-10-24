#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#
#   ./restore.sh backups/uaw-20261024T030000Z.dump
#       Restores into a separate database, uaw_restored, and prints its row counts
#       next to the live ones. The live database is not touched: use it to check that
#       a backup really restores (do it regularly, not on the day you need it).
#
#   ./restore.sh --replace backups/uaw-20261024T030000Z.dump
#       Replaces the live database with the backup: stops the API and the web server,
#       recreates the uaw database from the backup, then starts them again. Everything
#       written since the backup is lost.
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.prod.yml)

replace=false
if [[ "${1:-}" == "--replace" ]]; then
  replace=true
  shift
fi
file=${1:?usage: ./restore.sh [--replace] <backup file>}
[[ -f "$file" ]] || { echo "No such file: $file" >&2; exit 1; }

psql() { "${COMPOSE[@]}" exec -T db psql --username=uaw --no-psqlrc --tuples-only --no-align "$@"; }

counts() {
  psql --dbname="$1" --command="
    SELECT 'repositories', count(*) FROM repositories
    UNION ALL SELECT 'snapshots', count(*) FROM snapshots
    UNION ALL SELECT 'chunks', count(*) FROM chunks
    UNION ALL SELECT 'usage_records', count(*) FROM usage_records
    UNION ALL SELECT 'cached_answers', count(*) FROM cached_answers"
}

if [[ "$replace" == false ]]; then
  target=uaw_restored
  psql --dbname=postgres --command="DROP DATABASE IF EXISTS $target" > /dev/null
  psql --dbname=postgres --command="CREATE DATABASE $target OWNER uaw" > /dev/null
  "${COMPOSE[@]}" exec -T db pg_restore --username=uaw --dbname="$target" --no-owner --exit-on-error < "$file"
  echo "Restored $file into $target. Row counts (restored | live):"
  paste -d'|' <(counts "$target") <(counts uaw | cut -d'|' -f2)
  exit 0
fi

read -r -p "Replace the live database with $file? Everything since that backup is lost. Type 'replace': " answer
[[ "$answer" == "replace" ]] || { echo "Cancelled."; exit 1; }

"${COMPOSE[@]}" stop web api
psql --dbname=postgres --command="DROP DATABASE uaw WITH (FORCE)" > /dev/null
psql --dbname=postgres --command="CREATE DATABASE uaw OWNER uaw" > /dev/null
"${COMPOSE[@]}" exec -T db pg_restore --username=uaw --dbname=uaw --no-owner --exit-on-error < "$file"
"${COMPOSE[@]}" up -d --wait
echo "Live database replaced by $file. Row counts:"
counts uaw
