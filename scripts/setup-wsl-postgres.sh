#!/usr/bin/env bash
# Installs PostgreSQL 16 + pgvector in WSL (Debian) for local development, as a lighter
# alternative to Docker Desktop. Creates the same role and databases as docker-compose.yml.
# Safe to run several times. Credentials are for local development only.
set -euo pipefail

sudo apt-get update
sudo apt-get install -y postgresql-common ca-certificates
# Official PostgreSQL repository: Debian 12 ships PostgreSQL 15 and an old pgvector,
# the project needs pgvector >= 0.8 (hnsw.iterative_scan).
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16 postgresql-16-pgvector

sudo service postgresql start

sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN
     IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'uaw') THEN
       CREATE ROLE uaw LOGIN PASSWORD 'uaw';
     END IF;
   END \$\$;"

for db in uaw uaw_test; do
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'" | grep -q 1; then
    sudo -u postgres createdb -O uaw "$db"
  fi
  # pgvector is not a trusted extension: create it as superuser so uaw does not need to be one.
  sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$db" -c "CREATE EXTENSION IF NOT EXISTS vector"
done

sudo -u postgres psql -d uaw -tAc "SELECT 'pgvector ' || extversion FROM pg_extension WHERE extname = 'vector'"
echo "PostgreSQL is running on 127.0.0.1:5432. Stop it with: sudo service postgresql stop"
