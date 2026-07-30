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
receipt="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v payload="$payload" <<'SQL'
SELECT jsonb_pretty(casework.admit_evidence(:'payload'::jsonb));
SQL
)"

echo "── ingest receipt ─────────────────────────────"
echo "$receipt"

key="$(printf '%s' "$payload" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["external_key"])')"

echo "── exact-arm checkpoint ───────────────────────"
# Read as a persona, not as the connected login. Three reasons, in order of how
# badly each bites if you skip it:
#
#  1. workshop_participant holds no SELECT on casework.evidence_items -- by design
#     (A1: a bare SELECT raising permission denied is the first lesson). The
#     admit_evidence call above works because that function is SECURITY DEFINER;
#     this statement is outside it, so without SET LOCAL ROLE the Lab 1 finale
#     prints the receipt and then dies on "permission denied for table
#     evidence_items".
#  2. RLS is enforced on this table. Reading as a persona means the checkpoint
#     proves the admitted row is retrievable THROUGH the same enforcement path the
#     workshop later takes apart, not merely that a row was written.
#  3. persona_analyst specifically -- the least-privileged of the three. Payloads
#     default to acl {"visibility": "workshop"} (promote_pg_incident.py:41), so the
#     analyst can see them. If a future capture ships a restricted ACL, this
#     checkpoint SHOULD report not-visible: that is the enforcement working.
#
# SET LOCAL + ROLLBACK, never a session-level SET: read-only and self-undoing, and
# the same A3 envelope every _verify_sql in the app emits.
hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key' AND available_at <= now();
ROLLBACK;
SQL
)"
if [ "$hit" = "$key" ]; then
  echo "OK: ${key} is retrievable by the exact arm immediately"
else
  echo "REMEDY: ${key} not visible as-of now(); check available_at, that admit succeeded, and that sql/11_roles_rls.sql has been applied (this read runs as persona_analyst)" >&2
  exit 1
fi
