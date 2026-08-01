#!/usr/bin/env bash
#
# Produce the packaged restore artifact from an already-seeded database.
#
# The workshop's provisioning contract is a pg_restore, not a live embedding
# run: every participant stack must land the same Cohere Embed 4 vectors
# without calling a model at bootstrap. This script is how that artifact is
# built, and it is the only supported producer.
#
# Run it against a disposable database that has been through
#   make schema && make seed-casework CAPTURE_BUNDLE=...
# Never against the live workshop cluster.
#
# Usage:
#   DATABASE_URL=postgresql://... seed/dump.sh [output.dump]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${1:-$ROOT_DIR/seed/artifacts/hybrid-retrieval-seed-v2.dump}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set}"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: pg_dump not found on PATH. Install the PostgreSQL client tools." >&2
  exit 1
fi

# Refuse to dump an unready index. A dump taken mid-build restores a corpus that
# fails /ready on every participant stack, which is the expensive failure this
# guard exists to prevent.
echo "[dump] asserting search-index readiness"
psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 \
  -c "SELECT jsonb_pretty(retrieval.assert_search_index_ready());"

revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
if ! git -C "$ROOT_DIR" diff --quiet HEAD -- sql seed backend/app; then
  echo "ERROR: sql/, seed/, or backend/app/ has uncommitted changes." >&2
  echo "The archive records an immutable revision; commit first." >&2
  exit 1
fi

mkdir -p "$(dirname "$ARTIFACT")"

# Data and schema for the three owned schemas only. --no-owner/--no-privileges
# keeps the artifact portable across the author's roles and the workshop's;
# sql/11_roles_rls.sql owns the persona grants and runs separately.
echo "[dump] pg_dump -> $ARTIFACT"
pg_dump \
  --dbname="$DATABASE_URL" \
  --format=custom \
  --compress=9 \
  --schema=casework \
  --schema=retrieval \
  --schema=proof \
  --no-owner \
  --no-privileges \
  --file="$ARTIFACT"

# Stamp the producing revision into the artifact so seed/load.sh can refuse a
# dump whose schema generation does not match the checkout restoring it.
printf '%s\n' "$revision" > "$ARTIFACT.revision"

echo "[dump] revision: $revision"
echo "[dump] size: $(du -h "$ARTIFACT" | cut -f1)"
echo "[dump] done. Rebuild the Workshop Studio source archive from revision $revision."
