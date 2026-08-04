#!/usr/bin/env bash
# Package schema and application source. Participant evidence is never packaged.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT_DIR/dist/hybrid-retrieval-source.zip}"
REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD)"
STAGE="$(mktemp -d)"

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

if ! command -v zip >/dev/null 2>&1; then
  echo "ERROR: zip is required." >&2
  exit 1
fi

if ! git -C "$ROOT_DIR" diff --quiet HEAD -- \
  .claude admission backend frontend gates labs lambda_mcp mcp-server scripts sql Makefile
then
  echo "ERROR: runtime source has uncommitted changes; commit before packaging." >&2
  exit 1
fi

echo "[archive] exporting committed source at $REVISION"
git -C "$ROOT_DIR" archive "$REVISION" | tar -x -C "$STAGE"

# Tests and local mockups are not participant runtime.
rm -rf "$STAGE/mockups" "$STAGE/backend/tests"

for forbidden in admission design docs/superpowers seed; do
  if [ -e "$STAGE/$forbidden" ]; then
    echo "ERROR: retired fixture or authoring path entered archive: $forbidden" >&2
    exit 1
  fi
done

required=(
  backend/scripts/build_search_index.py
  labs/incident/capture_observability.py
  labs/incident/prepare_workload.py
  labs/incident/run_live_workshop.py
  labs/exercises/checkpoint.py
  labs/exercises/lab2-filter-request.json
  labs/exercises/lab2-fusion-request.json
  labs/exercises/lab2-rrf.sql
  labs/exercises/lab3-plan-request.json
  labs/exercises/lab3-traverse-request.json
  labs/exercises/lab3-compare-request.json
  .claude/skills/extend-hybrid-retrieval/SKILL.md
  sql/01_schema.sql
  sql/07_search_index_verification.sql
  sql/10_admission.sql
  sql/11_roles_rls.sql
  sql/12_masking.sql
  gates/checks.sh
  gates/rls_enforcement.py
  gates/masking_determinism.py
  gates/participant_ceremony.py
  gates/persona_equivalence.py
)
for path in "${required[@]}"; do
  if [ ! -f "$STAGE/$path" ]; then
    echo "ERROR: required live-path file missing: $path" >&2
    exit 1
  fi
done

if find "$STAGE" -type f \( \
  -name '*capture.json' -o \
  -name '*.dump' -o \
  -name '*.jsonl' -o \
  -name '*.sqlite' -o \
  -name '*.db' \
\) -print -quit | grep -q .; then
  echo "ERROR: archive contains generated evidence or database artifacts." >&2
  find "$STAGE" -type f \( \
    -name '*capture.json' -o \
    -name '*.dump' -o \
    -name '*.jsonl' -o \
    -name '*.sqlite' -o \
    -name '*.db' \
  \) -print >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
(cd "$STAGE" && zip -q -r -9 "$OUTPUT" .)
printf '%s\n' "$REVISION" | zip -q -z "$OUTPUT"

echo "[archive] revision: $REVISION"
echo "[archive] output:   $OUTPUT"
echo "[archive] evidence state: zero; bootstrap generates operational workload"
