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

mask_database_url() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

value = sys.argv[1]
parts = urlsplit(value)
if not parts.netloc:
    print(value)
    raise SystemExit(0)

host = parts.hostname or ""
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
netloc = host
if parts.port:
    netloc = f"{netloc}:{parts.port}"
if parts.username or parts.password:
    netloc = f"***:***@{netloc}"

print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
}

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore not found on PATH. Install the PostgreSQL client tools." >&2
  exit 1
fi
if [[ ! -f "$ARTIFACT" ]]; then
  echo "Seed artifact not found: $ARTIFACT" >&2
  echo "Run 'python seed/generate.py' first (with DATABASE_URL set) to build it." >&2
  exit 1
fi

echo "[load] target: $(mask_database_url "$DATABASE_URL")"
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

# 2b. Reconcile the object-level lexical vector BEFORE rebuilding indexes/functions.
#     The committed dump carries the OLD title-only column (title_tsv); sql/02 and
#     sql/03 below reference the NEW search_tsv column, so this must swap the schema
#     first or those steps fail on a missing column. Idempotent on a fresh schema.
echo "[load] reconciling object-level search_tsv column"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/12_search_tsv.sql"

# 2c. Add connector synchronization columns that are newer than the committed
#     dump. Full-sync connectors use these to tombstone missing source records
#     without deleting historical retrieval-candidate foreign keys.
echo "[load] reconciling connector synchronization columns"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/14_connector_sync.sql"

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

# 3b2. Re-apply corpus diagnostics so active/tombstoned connector rows are
#      reported correctly when restoring an older dump.
echo "[load] (re)applying corpus diagnostics"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/04_diagnostics.sql"

# 3c. Normalize participant-visible seed labels when restoring an older copy of
#     the committed dump. This is data-only and safe to re-run.
echo "[load] applying seed compatibility corrections"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/07_seed_corrections.sql"

# 3d. Add the pgvector 0.8 capability functions + halfvec/binary indexes. Pure
#     CREATE INDEX IF NOT EXISTS / CREATE OR REPLACE FUNCTION over the restored
#     embeddings, so it is additive and safe to re-run on any restored artifact.
echo "[load] (re)applying pgvector 0.8 functions + halfvec/binary indexes"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/08_pgvector_08.sql"

# 3e. Retrieval-quality metric functions (recall@k / MRR / nDCG) + comparison view.
#     Pure CREATE OR REPLACE FUNCTION / VIEW, additive and safe to re-run.
echo "[load] (re)applying evaluation metric functions"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/09_evaluation_metrics.sql"

# 3f. Query-plan + index/statistics surfaces (ops.query_plan, v_index_usage,
#     v_slow_queries). Pure CREATE OR REPLACE FUNCTION / VIEW, additive and safe.
echo "[load] (re)applying query-plan + statistics surfaces"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/10_query_plan.sql"

# 3g. Recursive object_links traversal (ops.traverse_links) — the cross-system
#     evidence walk that backs the graph/timeline and the agent's follow_evidence_links
#     tool. Pure CREATE OR REPLACE FUNCTION, additive and safe to re-run.
echo "[load] (re)applying recursive link traversal"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/11_traverse_links.sql"

# 3h. ACL demonstration seed — mark one non-canonical object (CASE-20919) as
#     restricted so row-level ACL enforcement (ops.acl_visible) is observable.
#     Data-only UPDATE, idempotent, and outside the canonical link component so the
#     "Why did Orion slip?" answer is unaffected.
echo "[load] applying ACL demonstration seed"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$ROOT_DIR/sql/13_acl_seed.sql"

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
