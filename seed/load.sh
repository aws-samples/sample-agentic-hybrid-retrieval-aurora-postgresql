#!/usr/bin/env bash
#
# Restore the packaged workshop corpus into Aurora PostgreSQL.
#
# This is the Workshop Studio provisioning path (SeedDatabase). It performs no
# embedding model calls: the Cohere Embed 4 vectors are baked into the artifact
# produced by seed/dump.sh, so every participant stack reuses the same vectors.
#
# Order matters:
#   1. extensions and schemas, so vector(1024) resolves during restore;
#   2. pg_restore of casework/retrieval/proof (data and tables);
#   3. the SQL function, view, and index definitions from this checkout;
#   4. ANALYZE, then a readiness assertion.
#
# Step 3 is deliberately re-applied from source rather than trusted from the
# dump: functions and views are the retrieval contract, and the checkout is
# authoritative for them. Tables and data are the dump's.
#
# Usage:
#   DATABASE_URL=postgresql://... seed/load.sh
#   seed/load.sh path/to/hybrid-retrieval-seed-v2.dump
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${1:-$ROOT_DIR/seed/artifacts/hybrid-retrieval-seed-v2.dump}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set (e.g. postgresql://localhost:55432/retrieval?sslmode=disable)}"

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | cut -d' ' -f1
  else
    echo "ERROR: sha256sum or shasum is required." >&2
    return 1
  fi
}

# Definitions re-applied over the restored data. This list intentionally omits
# sql/01_schema.sql: the dump carries the tables, and re-running DDL over
# restored rows is how column drift gets silently patched instead of caught.
DEFINITION_FILES=(
  sql/02_indexes.sql
  sql/03_search_functions.sql
  sql/04_diagnostics.sql
  sql/05_evaluation.sql
  sql/06_receipts.sql
  sql/07_search_index_verification.sql
  sql/08_query_runtime.sql
  sql/09_traverse_evidence.sql
  sql/10_admission.sql
)

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "ERROR: pg_restore not found on PATH. Install the PostgreSQL client tools." >&2
  exit 1
fi
sha256_file /dev/null >/dev/null
if [ ! -f "$ARTIFACT" ]; then
  echo "ERROR: seed artifact not found: $ARTIFACT" >&2
  echo "Produce it with 'DATABASE_URL=<disposable> seed/dump.sh' from a seeded database." >&2
  exit 1
fi

# Refuse bytes that do not match the producer's content sidecar. Zip integrity
# protects transfer; this check protects release assembly and manual restores.
if [ ! -f "$ARTIFACT.sha256" ]; then
  echo "ERROR: $ARTIFACT.sha256 missing; cannot verify seed artifact bytes." >&2
  exit 1
fi
expected_sha256="$(tr -d '[:space:]' < "$ARTIFACT.sha256")"
actual_sha256="$(sha256_file "$ARTIFACT")"
if [ "$actual_sha256" != "$expected_sha256" ]; then
  echo "ERROR: seed artifact checksum mismatch." >&2
  echo "Expected $expected_sha256 but read $actual_sha256." >&2
  exit 1
fi
echo "[load] artifact sha256: $actual_sha256"

# The artifact and this checkout must be the same schema generation. A dump from
# an older generation restores tables the current functions do not match, and
# the failure surfaces later as a wrong answer rather than a failed restore.
if [ -f "$ARTIFACT.revision" ]; then
  artifact_revision="$(tr -d '[:space:]' < "$ARTIFACT.revision")"
  if git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    checkout_revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
    if [ "$artifact_revision" != "$checkout_revision" ]; then
      echo "WARNING: artifact revision $artifact_revision does not match checkout $checkout_revision." >&2
      echo "WARNING: rebuild the artifact if the schema changed between them." >&2
    fi
  fi
  echo "[load] artifact revision: $artifact_revision"
else
  echo "WARNING: $ARTIFACT.revision missing; cannot verify the artifact's schema generation." >&2
fi

echo "[load] artifact: $ARTIFACT"

echo "[load] extensions and schemas"
psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -f "$ROOT_DIR/sql/00_extensions.sql"

# --clean --if-exists makes a re-run safe. --exit-on-error refuses a partial
# restore: a half-loaded corpus passes counts and fails citations.
echo "[load] pg_restore (tables and data)"
pg_restore \
  --dbname="$DATABASE_URL" \
  --schema=casework \
  --schema=retrieval \
  --schema=proof \
  --clean --if-exists \
  --no-owner --no-privileges \
  --exit-on-error \
  "$ARTIFACT"

echo "[load] re-applying indexes, functions, and views from this checkout"
for file in "${DEFINITION_FILES[@]}"; do
  echo "[load]   $file"
  psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -f "$ROOT_DIR/$file"
done

echo "[load] ANALYZE"
psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -c "
  ANALYZE casework.evidence_items;
  ANALYZE retrieval.documents;
  ANALYZE retrieval.chunks;
"

# The same assertion /ready and the facilitator preflight use. Failing here is
# the correct outcome for a bad restore: it stops provisioning instead of
# handing a participant a corpus that cannot answer the canonical question.
echo "[load] asserting search-index readiness"
psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 \
  -c "SELECT jsonb_pretty(retrieval.assert_search_index_ready());"

echo "[load] done."
