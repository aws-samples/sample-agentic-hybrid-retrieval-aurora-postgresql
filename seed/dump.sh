#!/usr/bin/env bash
#
# Produce the packaged restore artifact from an already-seeded database.
#
# The workshop's provisioning contract is a pg_restore, not a live embedding
# run: every participant stack must land the same Cohere Embed 4 vectors
# without calling a model at bootstrap. This script is how that artifact is
# built, and it is the only supported producer.
#
# Run it against a disposable database whose name ends in `_test` and that has
# been through
#   make schema && make seed-casework CAPTURE_BUNDLE=...
# Never against the live workshop cluster.
#
# Usage:
#   DATABASE_URL=postgresql://.../workbench_seed_test \
#     ALLOW_SEED_DUMP=1 seed/dump.sh [output.dump]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${1:-$ROOT_DIR/seed/artifacts/hybrid-retrieval-seed-v2.dump}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set}"
ALLOW_SEED_DUMP="${ALLOW_SEED_DUMP:-0}"

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

if [ "$ALLOW_SEED_DUMP" != "1" ]; then
  echo "ERROR: refusing to produce a seed dump without ALLOW_SEED_DUMP=1." >&2
  echo "Point DATABASE_URL at a disposable database whose name ends in '_test'," >&2
  echo "then set the explicit release-artifact guard." >&2
  exit 1
fi

for tool in psql pg_dump; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: $tool not found on PATH. Install the PostgreSQL client tools." >&2
    exit 1
  fi
done
sha256_file /dev/null >/dev/null

# Ask the server rather than parsing the DSN: URLs, service files, and keyword
# DSNs can all obscure the effective target. The suffix is the repository-wide
# disposable-database convention used by integration tests.
database_name="$(
  psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 \
    -c "SELECT current_database();"
)"
database_name="$(printf '%s' "$database_name" | tr -d '[:space:]')"
if [[ ! "$database_name" =~ _test$ ]]; then
  echo "ERROR: refusing to dump database '$database_name'." >&2
  echo "The database name must end in '_test' to prove it is disposable." >&2
  exit 1
fi
echo "[dump] disposable target: $database_name"

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
temp_artifact="$(mktemp "$ARTIFACT.tmp.XXXXXX")"
temp_revision="$temp_artifact.revision"
temp_sha256="$temp_artifact.sha256"
cleanup() {
  rm -f "$temp_artifact" "$temp_revision" "$temp_sha256"
}
trap cleanup EXIT

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
  --file="$temp_artifact"

# Stamp provenance and content identity only after pg_dump succeeds. Publishing
# the three files together prevents a failed producer from replacing a good
# artifact with a partial dump.
printf '%s\n' "$revision" > "$temp_revision"
sha256_file "$temp_artifact" > "$temp_sha256"
mv "$temp_artifact" "$ARTIFACT"
mv "$temp_revision" "$ARTIFACT.revision"
mv "$temp_sha256" "$ARTIFACT.sha256"

echo "[dump] revision: $revision"
echo "[dump] sha256: $(cat "$ARTIFACT.sha256")"
echo "[dump] size: $(du -h "$ARTIFACT" | cut -f1)"
echo "[dump] done. Rebuild the Workshop Studio source archive from revision $revision."
