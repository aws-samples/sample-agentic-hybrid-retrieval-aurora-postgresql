#!/usr/bin/env bash
# admit.sh — Lab 1 finale: promote a captured incident into the record (D23).
# Zero model calls. Prints the ingest receipt and the exact-arm checkpoint.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?set DATABASE_URL or add it to .env}"

payload="$(.venv/bin/python admission/promote_pg_incident.py "$@")"

# Admit inside a single statement; the function is itself one transaction.
# Piped via stdin (not -c): psql only substitutes :'var' inside SQL read from
# a script/stdin, not inside a -c command string.
receipt="$(psql "$DATABASE_URL" -X -q -t -A -v payload="$payload" <<'SQL'
SELECT jsonb_pretty(casework.admit_evidence(:'payload'::jsonb));
SQL
)"

echo "── ingest receipt ─────────────────────────────"
echo "$receipt"

key="$(printf '%s' "$payload" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["external_key"])')"

echo "── exact-arm checkpoint ───────────────────────"
hit="$(psql "$DATABASE_URL" -X -q -t -A \
  -c "SELECT external_key FROM casework.evidence_items WHERE external_key = '${key}' AND available_at <= now();")"
if [ "$hit" = "$key" ]; then
  echo "OK: ${key} is retrievable by the exact arm immediately"
else
  echo "REMEDY: ${key} not visible as-of now(); check available_at and that admit succeeded" >&2
  exit 1
fi
