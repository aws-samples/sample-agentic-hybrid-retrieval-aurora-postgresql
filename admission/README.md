# Admission contract (D21)

This directory is the write boundary for admitting a single piece of captured
evidence into the canonical record without going through the bulk corpus
loader. It exists for the Lab 1 finale: a participant captures a real lock
event during the session and promotes it into the same tables the rest of
the workshop retrieves from.

## The contract

The entry point is one PostgreSQL function:

```sql
casework.admit_evidence(payload jsonb) RETURNS jsonb
```

defined in `sql/10_admission.sql`. The whole admission is one transaction: it
validates the payload, resolves the referenced incident, upserts the
canonical `casework.evidence_items` header and the typed `casework.lock_evidence`
detail row, records any resolvable links as `retrieval.inferred_edges`, queues
the row for the search-index build (`retrieval.search_index_queue`), and
returns an ingest receipt from `casework.ingest_receipts`. Any contract
violation raises and rolls back every write in that call — admission never
leaves a half-written row behind.

There is no HTTP endpoint for this. The function is the boundary; call it
from `psql`, from a script, or from a backend job — whatever caller you
write, it goes through `admit_evidence`, not through hand-written INSERTs
against `casework.evidence_items`.

## The `payload v1` shape

The JSON Schema is checked in at `admission/payload_v1.schema.json`
(`admission payload v1`, draft 2020-12). A worked example that the function
accepts as-is is `admission/fixture_payload.json`. In short, a payload names
its schema version, a `source` (system + URI, used for idempotency), a
`kind` (currently `lock_evidence` is the only implemented contract path),
an `external_key`, human-readable `title`/`body`, an `occurred_at`
timestamp, an optional `available_at` gate, an `acl`, a `structured` object
carrying the kind-specific typed fields, and an optional `links` array for
inferred relationships to other evidence.

## The JSONB-doorway rule

`payload` arrives as one `jsonb` blob, but the function does not store it as
one. Anything a retrieval arm filters on, or a join walks, is pulled out into
a real typed column before the transaction commits — `relation_name`,
`blocked_pid`, `blocking_pid`, `wait_event_type`, and so on all live in
`casework.lock_evidence` as ordinary columns, not buried in a jsonb field.
Only the parts nothing joins or filters on (`raw_capture`) stay jsonb. If you
add a new `promote_*` adapter and a query ever needs to select or join on a
field you left inside jsonb, that is the signal to add it as a column and
extend the contract function — not to reach for a jsonb operator in the
retrieval SQL.

## Idempotency

Admission is idempotent by `(source_uri, content_hash)`. The content hash is a
fingerprint of the normalized complete payload, including structured facts,
ACL, links, and availability. Calling `admit_evidence` twice with the same
payload does no second write: the function returns the prior receipt with
`idempotent_replay: true` and the same `ingest_id`. A changed measurement under
the same source URI creates a new receipt and updates the stable evidence row.

## The `available_at` gate

`available_at` (default: `now()` at admission time if the payload omits it)
is a real column on `casework.evidence_items`, and every retrieval arm that
should honor "don't surface evidence before it was actually available" filters
on `available_at <= now()`. Setting `available_at` in the future lets you
admit evidence that only becomes retrievable later; leaving it unset (or in
the past) makes it visible in canonical casework immediately, which is what the
checkpoint in `admit.sh` verifies.

## Zero model calls; retrieval projection is queued, not synchronous

Admission never calls Bedrock and never blocks on embedding generation.
`admit_evidence` only inserts a row into `retrieval.search_index_queue`; a
separate, later build pass (the same search-index builder the bulk loader
uses — see `docs/ingestion-api.md`) is what turns a queued row into a
`retrieval.documents`/`retrieval.chunks` projection with embeddings.
`admit.sh` checks the authoritative `casework.evidence_items` row and ACL
predicate only. Exact, lexical, semantic, fuzzy, and hybrid retrieval over the
newly admitted evidence are not live until the next search-index build runs.

## Files here

- `promote_pg_incident.py` — the reference `promote_*` adapter. Stdlib only,
  no database connection. It reads a live capture directory (default
  `/run/workbench/lock_capture.json`) if one exists; otherwise it falls back to
  `fixture_payload.json` and says so on stderr. It never fabricates a
  capture — the fallback path is truthful about which one it took.
- `admit.sh` — the Lab 1 finale script. Requires `DATABASE_URL` in the
  environment, runs the promoter, pipes the resulting payload into
  `casework.admit_evidence` via `psql`, prints the ingest receipt, and then
  runs the canonical-row checkpoint (confirms the admitted `external_key` is
  selectable from `casework.evidence_items` as of `now()` through the ACL
  predicate). With `WORKBENCH_SECURITY_ENABLED=1`, the same checkpoint also
  runs as `persona_app_engineer` through live RLS.
- `fixture_payload.json` — the deterministic `LOCK-LIVE-001` payload used
  when no live capture is present.
- `payload_v1.schema.json` — the JSON Schema for `admission payload v1`.

## Writing your own `promote_*` adapter

To admit a different capture source, write a new `promote_<source>.py` next
to `promote_pg_incident.py` following the same shape:

1. Stdlib only (or a dependency you have already justified elsewhere in the
   repo) — no new third-party dependency just for an adapter.
2. Never touch the database. The adapter's only job is to produce one
   `admission payload v1` JSON document on stdout.
3. Never fabricate data. If the live source you're reading from isn't
   present, fall back to a checked-in fixture and say so on stderr, exactly
   as `promote_pg_incident.py` does — don't synthesize a payload that looks
   real.
4. Reuse `admit.sh` unchanged: it only cares that its first positional
   arguments are accepted by whatever promoter you point it at and that the
   promoter's stdout is a valid `admission payload v1` document. Point a copy
   of `admit.sh` (or a thin wrapper) at your new promoter's path instead of
   `promote_pg_incident.py`.
5. Every field your adapter maps from the raw source into `structured` that a
   retrieval arm will need to filter or join on has to land as a real column
   in `casework.admit_evidence` (see the JSONB-doorway rule above) — extend
   the SQL function for your `kind`, don't smuggle new query needs through
   jsonb.

Payloads default `acl` to `{"visibility": "workshop"}`, matching the
core scope documented in `docs/data-model.md`. A payload admitted with
`{"visibility": "restricted"}` is excluded by the core ACL predicate. In the
optional security module it is also invisible to the App Engineer through RLS,
so the checkpoint reporting it as not visible is correct behavior rather than a
failed admission.
