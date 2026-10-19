#!/usr/bin/env bash
# Runs once, on the very first boot of an EMPTY data volume.
# If you change anything in db/init/, you must `make nuke` (drops the volume) to re-run it.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v app_pw="${APP_DB_PASSWORD:-shop_app_pw}" \
  -v worker_pw="${WORKER_DB_PASSWORD:-shop_worker_pw}" <<'SQL'
CREATE ROLE shop_app    LOGIN PASSWORD :'app_pw';
CREATE ROLE shop_worker LOGIN PASSWORD :'worker_pw';
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
