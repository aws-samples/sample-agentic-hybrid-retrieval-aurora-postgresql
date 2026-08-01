#!/usr/bin/env bash
# admit.sh - Lab 1 finale: promote a captured incident into the record (D23).
# Zero model calls. Prints the ingest receipt and canonical-row checkpoint.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?set DATABASE_URL or add it to .env}"

# A local checkout installs into .venv; the Workshop Studio Code Editor installs
# with `pip install --user` and has no venv. Prefer the venv when it exists so a
# developer machine keeps using its pinned interpreter.
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "ERROR: no interpreter found; expected .venv/bin/python or python3 on PATH" >&2
  exit 1
fi

payload="$("$PYTHON" admission/promote_pg_incident.py "$@")"

# Admit inside a single statement; the function is itself one transaction.
# Piped via stdin (not -c): psql only substitutes :'var' inside SQL read from
# a script/stdin, not inside a -c command string.
receipt="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v payload="$payload" <<'SQL'
SELECT jsonb_pretty(casework.admit_evidence(:'payload'::jsonb));
SQL
)"

echo "ingest receipt"
echo "$receipt"

key="$(printf '%s' "$payload" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["external_key"])')"

echo "canonical evidence checkpoint"
# This proves admission and ACL visibility at the authoritative row. Hybrid
# retrieval begins only after the queued row is projected into retrieval.*
# with a compatible embedding.
security_enabled="${WORKBENCH_SECURITY_ENABLED:-0}"
if [[ "$security_enabled" =~ ^(1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn])$ ]]; then
  hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
BEGIN;
SET LOCAL ROLE persona_app_engineer;
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key'
   AND available_at <= now()
   AND retrieval.acl_visible(acl);
ROLLBACK;
SQL
  )"
else
  hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key'
   AND available_at <= now()
   AND retrieval.acl_visible(acl);
SQL
  )"
fi
if [ "$hit" = "$key" ]; then
  echo "OK: ${key} is admitted and visible in canonical casework"
else
  echo "REMEDY: ${key} not visible in canonical casework; check available_at, admission, and ACL visibility" >&2
  exit 1
fi
