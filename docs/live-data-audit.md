# Live-data audit

This audit records every pre-existing source of fixture, snapshot, canned, or
authored incident data that could be mistaken for participant evidence. The
standing participant contract is stricter: only telemetry produced by the
participant's current `make live-workshop` run may enter retrieval. The Overview
page's main graphic is the sole illustrative exception and never enters
`casework`, `retrieval`, or `proof`.

Workshop bootstrap generates 5,000 disposable `workbench_lab.customers` rows
and 3,000,000 related `workbench_lab.orders` rows while the evidence store is
empty. Those operational rows make the incident real but are not participant
evidence.

## Participant path after the refactor

`labs/incident/run_live_workshop.py` is the only incident producer. It:

1. validates and reuses the preloaded operational tables on the participant's
   Aurora database;
2. induces an ordinary `CREATE INDEX` write stall with six real writers and two
   real readers;
3. captures 30 live PostgreSQL observation windows;
4. collects CloudWatch and Performance Insights rows for that exact window;
5. applies and measures `CREATE INDEX CONCURRENTLY`;
6. builds run-derived searchable evidence only from those measurements;
7. invokes Cohere Embed through Bedrock for every current chunk; and
8. publishes a receipt only after provenance, scale, and embedding checks pass.

No support cases, runbooks, postmortems, customer records, company names, person
names, or authored distractors are admitted. The searchable corpus contains
only the incident, the measured unsafe and repair changes, the primary lock
observation, and searchable records built deterministically from measured telemetry.

## Legacy data inventory

| Legacy location | Data previously supplied | Participant-path resolution |
|---|---|---|
| `seed/corpus.py` | Authored incidents, changes, cases, runbooks, postmortems, people, companies, and distractors | Deleted |
| `seed/capture.py` | Offline PostgreSQL activity, lock, blocking-PID, and statement captures | Deleted; replaced by the live orchestrator |
| `seed/artifacts/` | Pre-generated embedding manifest and former dump inputs | Deleted |
| `seed/load.sh`, `seed/dump.sh` | Restore and production of a preloaded corpus | Deleted; replaced by an evidence-free source archive, bootstrap-generated operational workload, and live admission |
| `admission/fixture_payload.json` | Three-record canned admission bundle | Deleted |
| `admission/promote_pg_incident.py`, `admission/admit.sh` | Fixed-ID promotion of multi-terminal JSON captures | Deleted; replaced by in-process run-scoped evidence build and admission |
| `labs/incident/00_setup.sql` through `99_cleanup.sql` | Fixed-ID multi-terminal capture workflow and static capture filenames | Deleted; replaced by one guided orchestrator |
| `backend/scripts/capture_release_aurora.py` | Release-time Aurora snapshot for later reuse | Deleted; replaced by per-participant collection |
| `scripts/build_source_archive.sh` | Archive containing a prebuilt seed dump | Deleted; replaced by `scripts/build_live_source_archive.sh` |
| `design/verity/fixtures/` and design capture JSON | Generated UI and transport fixture records | Deleted; the approved Overview illustration is owned by Workshop Studio |
| `gates/baselines/` and old fixed-ID gates | Expected results tied to the authored corpus | Deleted; replaced by run-derived live gates |
| `backend/tests/payload_factory.py` | Generated but unmeasured telemetry rows for admission tests | Deleted; admission tests require `LIVE_CAPTURE_PAYLOAD` from a real run |
| `data/generated/incident-lab/*` and `data/generated/release-aurora-capture.json` | Ignored local outputs from earlier runs | Never committed or packaged; generated outputs must be cleared between participant sessions |
| Workshop Studio seed dump and packaged source archive | Preloaded participant database state | The archive contains source but no database state; bootstrap generates only the disposable workload before live admission |

## Identifier cleanup

The retired authored IDs and their supporting design, security lesson, fixture,
and baseline files have been deleted. Participant-facing source accepts only
capture-derived `INC-*`, `CHG-*`, `LOCK-*`, and `TEL-*` identifiers.

## Live verification

The clean Aurora validation run used capture
`6949b1ef-03b7-41e7-8def-3518478fd535` (`478FD535`) on PostgreSQL 18.3. Its
receipt reported:

- 110 searchable documents and 110 chunks;
- 110 Cohere embeddings generated at runtime with zero cache hits;
- 270 `pg_stat_activity` rows;
- 270 `pg_locks` rows;
- 180 `pg_blocking_pids` rows;
- three `pg_stat_statements` phase rows;
- five CloudWatch metric rows; and
- seven Performance Insights observations.

The live retrieval contract confirmed that every participant-facing row belongs
to that capture and source URI. The core gates passed against its run-derived
IDs, and G-13 replayed every receipt panel, 216 graph edges, and 110 timeline
events from the published SQL.
