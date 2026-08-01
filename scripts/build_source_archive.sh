#!/usr/bin/env bash
#
# Build the Workshop Studio source archive.
#
# The archive is what CFN PrepareWorkshopSource downloads, unzips, and copies
# into the participant's home folder, and SeedDatabase then runs
# seed/load.sh out of it. Until this script existed the archive was assembled
# by hand, which is how the published one ended up five schema generations
# behind the repository: its dump carried only the deleted `ops` schema, so
# the current seed/load.sh would have restored zero tables.
#
# Two properties make that failure impossible here:
#
#   1. the source half comes from `git archive`, so the archive contains
#      exactly one committed revision and cannot pick up local edits; and
#   2. the dump half is verified to contain the three schemas seed/load.sh
#      restores, and to have been produced by the same revision.
#
# Usage:
#   scripts/build_source_archive.sh [output.zip]
#
# Requires the seed artifact plus its .revision and .sha256 sidecars:
#   DATABASE_URL=<disposable_test> ALLOW_SEED_DUMP=1 make seed-dump
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT_DIR/dist/hybrid-retrieval-source.zip}"
DEFAULT_ARTIFACT="$ROOT_DIR/seed/artifacts/hybrid-retrieval-seed-v2.dump"
ARTIFACT="${SEED_ARTIFACT:-$DEFAULT_ARTIFACT}"
CANONICAL_ARTIFACT_REL="seed/artifacts/hybrid-retrieval-seed-v2.dump"

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

# Paths tracked in git that the participant environment must not receive.
# Everything else tracked at HEAD ships: the guide runs labs/, admission/,
# gates/, and agent/ directly out of the unpacked archive.
EXCLUDE_FROM_ARCHIVE=(
  design           # UI mockups and the spec workspace; 1.8 MB, no runtime reader
  docs/superpowers # design specs and implementation plans; authoring history
)

# Paths the guide instructs participants to open or run. Their absence is a
# broken workshop, so the build fails rather than publishing a quiet gap.
REQUIRED_IN_ARCHIVE=(
  .env.example
  Makefile
  admission/admit.sh
  agent/registry.py
  backend/requirements.txt
  frontend/package.json
  frontend/package-lock.json
  gates/checks.sh
  labs/incident/00_setup.sql
  labs/incident/10_unsafe_index.sql
  labs/incident/20_blocked_writer.sql
  labs/incident/30_observe_unsafe.sql
  labs/incident/40_safe_writer.sql
  labs/incident/50_concurrent_index.sql
  labs/incident/60_observe_safe.sql
  labs/incident/70_verify.sql
  labs/incident/99_cleanup.sql
  labs/exercises/checkpoint.py
  labs/exercises/lab2-filter-request.json
  labs/exercises/lab2-fusion-request.json
  labs/exercises/lab2-rrf.sql
  labs/exercises/lab3-plan-request.json
  labs/exercises/lab3-traverse-request.json
  labs/exercises/lab3-compare-request.json
  lambda_mcp/handler.py
  gates/rls_enforcement.py
  gates/masking_determinism.py
  gates/participant_ceremony.py
  gates/persona_equivalence.py
  scripts/invoke_agentcore_gateway.py
  seed/artifacts/hybrid-retrieval-seed-v2.dump
  seed/artifacts/hybrid-retrieval-seed-v2.dump.revision
  seed/artifacts/hybrid-retrieval-seed-v2.dump.sha256
  seed/load.sh
  sql/01_schema.sql
  sql/03_search_functions.sql
  sql/11_roles_rls.sql
  sql/12_masking.sql
)

# Schemas seed/load.sh passes to pg_restore. A dump missing any of them
# restores nothing for that schema and provisioning "succeeds" empty.
REQUIRED_DUMP_SCHEMAS=(casework retrieval proof)

for tool in git zip unzip pg_restore; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: $tool not found on PATH." >&2
    exit 1
  fi
done
sha256_file /dev/null >/dev/null

# The archive comment records an immutable revision, so it must describe a
# committed tree. Uncommitted work would ship under a revision that does not
# contain it.
if ! git -C "$ROOT_DIR" diff --quiet HEAD; then
  echo "ERROR: the worktree has uncommitted changes." >&2
  echo "The archive records an immutable revision; commit first." >&2
  exit 1
fi
revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"

# git archive ships HEAD, so untracked files are omitted. That is the intent,
# but silently dropping a file the maintainer believed was shipping is how the
# published archive lost labs/ in the first place. Name the top-level entries
# rather than every file, so the warning stays readable.
untracked="$(git -C "$ROOT_DIR" ls-files --others --exclude-standard \
  | cut -d/ -f1 | sort -u)"
if [ -n "$untracked" ]; then
  echo "WARNING: untracked paths are NOT in the archive (git archive ships HEAD):" >&2
  while IFS= read -r path; do echo "  $path" >&2; done <<<"$untracked"
fi

if [ ! -f "$ARTIFACT" ]; then
  echo "ERROR: seed artifact not found: $ARTIFACT" >&2
  echo "Produce it first with:" >&2
  echo "  DATABASE_URL=<disposable_test> ALLOW_SEED_DUMP=1 make seed-dump" >&2
  exit 1
fi
if [ ! -f "$ARTIFACT.revision" ]; then
  echo "ERROR: $ARTIFACT.revision missing." >&2
  echo "Rebuild the artifact so its schema generation can be verified." >&2
  exit 1
fi
if [ ! -f "$ARTIFACT.sha256" ]; then
  echo "ERROR: $ARTIFACT.sha256 missing." >&2
  echo "Rebuild the artifact so its bytes can be verified." >&2
  exit 1
fi

# seed/load.sh only warns on a revision mismatch, because a participant stack
# cannot recover from a hard failure at 2am. The release path is where the
# mismatch is still cheap to fix, so here it is fatal.
artifact_revision="$(tr -d '[:space:]' < "$ARTIFACT.revision")"
if [ "$artifact_revision" != "$revision" ]; then
  echo "ERROR: artifact revision $artifact_revision does not match HEAD $revision." >&2
  echo "Rebuild the artifact from this revision with:" >&2
  echo "  DATABASE_URL=<disposable_test> ALLOW_SEED_DUMP=1 make seed-dump" >&2
  exit 1
fi

expected_sha256="$(tr -d '[:space:]' < "$ARTIFACT.sha256")"
actual_sha256="$(sha256_file "$ARTIFACT")"
if [ "$actual_sha256" != "$expected_sha256" ]; then
  echo "ERROR: seed artifact checksum mismatch." >&2
  echo "Expected $expected_sha256 but read $actual_sha256." >&2
  exit 1
fi

echo "[archive] verifying the dump carries the schemas seed/load.sh restores"
dump_toc="$(pg_restore -l "$ARTIFACT")"
for schema in "${REQUIRED_DUMP_SCHEMAS[@]}"; do
  if ! grep -q "TABLE DATA $schema " <<<"$dump_toc"; then
    echo "ERROR: the dump contains no TABLE DATA for schema '$schema'." >&2
    echo "seed/load.sh restores casework, retrieval, and proof; this dump" >&2
    echo "would restore an empty database. Rebuild it with:" >&2
    echo "  DATABASE_URL=<disposable_test> ALLOW_SEED_DUMP=1 make seed-dump" >&2
    exit 1
  fi
done

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/hybrid-retrieval-archive-XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "[archive] git archive $revision"
git -C "$ROOT_DIR" archive --format=tar "$revision" | tar -x -C "$STAGE"

for path in "${EXCLUDE_FROM_ARCHIVE[@]}"; do
  echo "[archive]   excluding $path"
  rm -rf "${STAGE:?}/${path:?}"
done

# The dump and its sidecar are gitignored -- they are release artifacts, not
# source -- so git archive cannot carry them. This is the only content in the
# archive that does not come from the committed tree.
echo "[archive] injecting the seed artifact"
mkdir -p "$STAGE/seed/artifacts"
cp "$ARTIFACT" "$STAGE/$CANONICAL_ARTIFACT_REL"
cp "$ARTIFACT.revision" "$STAGE/$CANONICAL_ARTIFACT_REL.revision"
cp "$ARTIFACT.sha256" "$STAGE/$CANONICAL_ARTIFACT_REL.sha256"

staged_sha256="$(
  sha256_file "$STAGE/$CANONICAL_ARTIFACT_REL"
)"
if [ "$staged_sha256" != "$expected_sha256" ]; then
  echo "ERROR: staged seed artifact checksum mismatch." >&2
  exit 1
fi

for path in "${REQUIRED_IN_ARCHIVE[@]}"; do
  if [ ! -e "$STAGE/$path" ]; then
    echo "ERROR: required path missing from the archive: $path" >&2
    exit 1
  fi
done

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
echo "[archive] zip -> $OUTPUT"
(cd "$STAGE" && zip -q -r -9 "$OUTPUT" .)

# The comment is how a published archive is traced back to its revision.
# assets/README.md in the guide repository reads it during release review.
printf '%s\n' "$revision" | zip -q -z "$OUTPUT"

echo "[archive] revision: $revision"
echo "[archive] size:     $(du -h "$OUTPUT" | cut -f1)"
echo "[archive] sha256:    $(sha256_file "$OUTPUT")"
echo "[archive] done. Upload to the Workshop Studio assets bucket as"
echo "[archive] hybrid-retrieval-source.zip and record the revision above."
