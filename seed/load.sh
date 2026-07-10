#!/usr/bin/env bash
#
# Idempotent restore of the workshop seed into Aurora / local Postgres.
#
# What it does, in order:
#   1. Ensures extensions + schema exist (safe to re-run).
#   2. pg_restore of the -Fc artifact into the `ops` schema (data + tables).
#   3. Rebuilds the ANN + lexical indexes AFTER the data load, so the HNSW graph
#      is built once over the full vector set (much faster than incremental):
#        - HNSW on object_chunks.embedding (m=16, ef_construction=64, cosine)
#        - GIN on the generated tsvector columns (full-text)
#        - GIN trigram on title + chunk_text (fuzzy)
#   4. ANALYZE so the planner has fresh stats.
#
# Re-running is safe: --clean drops seeded tables first; CREATE INDEX guards on
# IF NOT EXISTS; the artifact carries the same deterministic rows every time.
#
# Usage:
#   DATABASE_URL=postgresql://... seed/load.sh
#   seed/load.sh path/to/hybrid-retrieval-seed-v1.dump
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${1:-$ROOT_DIR/seed/artifacts/hybrid-retrieval-seed-v1.dump}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set (e.g. postgresql://localhost:55432/retrieval?sslmode=disable)}"

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore not found on PATH. Install the PostgreSQL client tools." >&2
  exit 1
fi
if [[ ! -f "$ARTIFACT" ]]; then
  echo "Seed artifact not found: $ARTIFACT" >&2
  echo "Run 'python seed/generate.py' first (with DATABASE_URL set) to build it." >&2
  exit 1
fi

echo "[load] target: $DATABASE_URL"
echo "[load] artifact: $ARTIFACT"

# 1. Extensions + schema (idempotent). Extensions must exist before restore so
#    the vector(1024) column type resolves.
echo "[load] ensuring extensions + schema"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/00_extensions.sql"

# 2. Restore data. --clean --if-exists makes re-runs safe; --no-owner/--no-acl
#    keep it portable across the seed author and the workshop DB roles.
echo "[load] pg_restore (data + tables)"
pg_restore \
  --dbname="$DATABASE_URL" \
  --schema=ops \
  --clean --if-exists \
  --no-owner --no-privileges \
  --exit-on-error \
  "$ARTIFACT"

# 3. Rebuild indexes AFTER the load. The dump is taken with the indexes in
#    place, but we (re)assert them here so a JSONL-only or partial load also
#    ends up correctly indexed. All guarded by IF NOT EXISTS.
echo "[load] (re)building HNSW + GIN + trigram indexes"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/02_indexes.sql"

# 3b. Re-apply the search functions. They are baked into the dump, but re-running
#     03 (pure CREATE OR REPLACE FUNCTION — no tables, no data) upgrades an older
#     restored artifact in place, so the current lexical/RRF logic always wins.
echo "[load] (re)applying search functions"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/03_search_functions.sql"

# 4. Fresh planner stats.
echo "[load] ANALYZE"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "ANALYZE ops.source_objects; ANALYZE ops.object_chunks; ANALYZE ops.object_links;"

# Report what landed.
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "
  SELECT
    (SELECT count(*) FROM ops.source_objects)  AS source_objects,
    (SELECT count(*) FROM ops.object_chunks)   AS chunks,
    (SELECT count(*) FROM ops.object_chunks WHERE embedding IS NOT NULL) AS embedded_chunks,
    (SELECT count(*) FROM ops.object_links)    AS links,
    (SELECT count(*) FROM ops.agent_answers)   AS agent_answers,
    (SELECT count(*) FROM ops.retrieval_candidates) AS candidates;
"

echo "[load] done."
