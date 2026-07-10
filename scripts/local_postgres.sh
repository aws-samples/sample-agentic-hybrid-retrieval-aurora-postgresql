#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_HOME="${POSTGRES_HOME:-/usr/local/opt/postgresql@18}"
if [[ -x "$POSTGRES_HOME/bin/postgres" ]]; then
  export PATH="$POSTGRES_HOME/bin:$PATH"
fi
PGDATA="${PGDATA:-$ROOT_DIR/.postgres-data-18}"
PGPORT="${PGPORT:-55432}"
PGDATABASE="${PGDATABASE:-retrieval}"
PGLOG="${PGLOG:-$ROOT_DIR/.postgres.log}"
DATABASE_URL="${DATABASE_URL:-postgresql://localhost:$PGPORT/$PGDATABASE?sslmode=disable}"
PYTHON_BIN="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
POSTGRES_MIN_VERSION="${POSTGRES_MIN_VERSION:-18.3}"
PGVECTOR_MIN_VERSION="${PGVECTOR_MIN_VERSION:-0.8.1}"
SQL_FILES=(
  sql/00_extensions.sql
  sql/01_schema.sql
  sql/02_indexes.sql
  sql/03_search_functions.sql
  sql/04_diagnostics.sql
  sql/05_evaluation.sql
)

export DATABASE_URL

ensure_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 was not found on PATH." >&2
    exit 1
  fi
}

version_ge() {
  awk -v actual="$1" -v required="$2" 'BEGIN {
    split(actual, a, ".");
    split(required, b, ".");
    for (i = 1; i <= 3; i++) {
      ai = a[i] + 0;
      bi = b[i] + 0;
      if (ai > bi) exit 0;
      if (ai < bi) exit 1;
    }
    exit 0;
  }'
}

ensure_postgres_version() {
  ensure_tool postgres
  actual="$(postgres --version | sed -E 's/.* ([0-9]+(\.[0-9]+)?).*/\1/')"
  if ! version_ge "$actual" "$POSTGRES_MIN_VERSION"; then
    echo "Local postgres binary is $actual; expected >= $POSTGRES_MIN_VERSION." >&2
    echo "Install PostgreSQL 18.3 or later with Homebrew, or use the Docker Compose path." >&2
    exit 1
  fi
  required_major="${POSTGRES_MIN_VERSION%%.*}"
  if [[ -f "$PGDATA/PG_VERSION" ]]; then
    data_major="$(cat "$PGDATA/PG_VERSION")"
    if [[ "$data_major" != "$required_major" ]]; then
      echo "$PGDATA was initialized with PostgreSQL $data_major; expected major $required_major." >&2
      echo "Use a different PGDATA or remove the old local data directory before bootstrapping PostgreSQL $POSTGRES_MIN_VERSION." >&2
      exit 1
    fi
  fi
}

init_db() {
  ensure_tool initdb
  ensure_postgres_version
  if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    LC_ALL=C LANG=C initdb -D "$PGDATA" --auth=trust --encoding=UTF8 --locale=C
    {
      echo "shared_preload_libraries = 'pg_stat_statements'"
      echo "listen_addresses = 'localhost'"
    } >> "$PGDATA/postgresql.conf"
  fi
}

start_db() {
  ensure_tool pg_ctl
  ensure_postgres_version
  init_db
  if pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
    echo "Postgres is already running from $PGDATA"
  else
    pg_ctl -D "$PGDATA" -l "$PGLOG" -o "-p $PGPORT" start
  fi
}

stop_db() {
  ensure_tool pg_ctl
  if [[ -f "$PGDATA/PG_VERSION" ]]; then
    pg_ctl -D "$PGDATA" stop -m fast
  fi
}

create_database() {
  ensure_tool createdb
  createdb -h localhost -p "$PGPORT" "$PGDATABASE" >/dev/null 2>&1 || true
}

run_schema() {
  "$PYTHON_BIN" backend/scripts/check_postgres.py --min-version "$POSTGRES_MIN_VERSION"
  "$PYTHON_BIN" backend/scripts/check_pgvector.py --available --min-version "$PGVECTOR_MIN_VERSION"
  "$PYTHON_BIN" backend/scripts/run_sql.py --files "${SQL_FILES[@]}"
  "$PYTHON_BIN" backend/scripts/check_pgvector.py --min-version "$PGVECTOR_MIN_VERSION"
}

load_seed() {
  # Restore the canonical workshop corpus from the prebuilt -Fc dump: 150 objects
  # (30 each across Slack, Jira, Confluence, Salesforce, GitHub) with REAL Cohere
  # embed-v4 (1024-d) vectors, the stored cited answer, links, and diagnostics
  # rows baked in. No hash stub and no Bedrock calls at load time — every run
  # reuses the same one-time embeddings. seed/load.sh reads DATABASE_URL (exported
  # above) and rebuilds the HNSW/GIN/trigram indexes after restore.
  seed/load.sh
}

case "${1:-help}" in
  init)
    init_db
    ;;
  start)
    start_db
    create_database
    echo "DATABASE_URL=$DATABASE_URL"
    ;;
  stop)
    stop_db
    ;;
  status)
    pg_ctl -D "$PGDATA" status
    ;;
  schema)
    run_schema
    ;;
  load-sample)
    load_seed
    ;;
  load-seed)
    load_seed
    ;;
  bootstrap)
    start_db
    create_database
    run_schema
    load_seed
    echo "Local Postgres is ready: $DATABASE_URL"
    ;;
  *)
    cat <<USAGE
Usage: scripts/local_postgres.sh <command>

Commands:
  init          Initialize .postgres-data
  start         Start local Postgres and create the retrieval database
  stop          Stop local Postgres
  status        Show local Postgres status
  schema        Install extensions, schema, indexes, functions, diagnostics
  load-seed     Restore the canonical Cohere-embedded seed dump (seed/load.sh)
  load-sample   Alias for load-seed (kept for compatibility)
  bootstrap     Start, create schema, restore the seed dump, rebuild indexes

Environment:
  PGPORT=$PGPORT
  PGDATABASE=$PGDATABASE
  POSTGRES_MIN_VERSION=$POSTGRES_MIN_VERSION
  PGVECTOR_MIN_VERSION=$PGVECTOR_MIN_VERSION
  DATABASE_URL=$DATABASE_URL
USAGE
    ;;
esac
