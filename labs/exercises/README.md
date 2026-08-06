# Participant Exercises

These files turn Labs 2 through 4 into bounded build exercises without asking
participants to rewrite the retrieval engine or agent framework.

- `lab2-sql-retrieval.sql` is generated with the current Investigation Evidence identifiers.
  It inspects the physical indexes and runs exact, full-text, pgvector, and
  `pg_trgm` retrieval, then makes the participant add the pre-fusion change
  filter and inspect the live plans.
- `lab2-filter-request.json` returns mixed live evidence so the participant can
  add `kinds: ["change"]` and prove pre-fusion filtering.
- `lab2-fusion-request.json` carries the default weighted-RRF controls.
- `lab2-rrf.sql` contains the participant-written fusion expression and a
  fail-closed receipt checkpoint.
- `lab3-plan-request.json` asks the three-part, run-derived diagnostic question:
  backfill/write stall, pool exhaustion and recovery, then the plan regression
  that `ANALYZE` did not resolve. It distinguishes the Investigation Evidence-backed
  bounded-backfill guidance for future migrations from the post-index outcome
  that remains unavailable until Validation Evidence.
- `lab3-traverse-request.json` and `lab3-compare-request.json` are populated
  from the current run's receipt by `make live-workshop`. Complete the Lab 2
  and Lab 3 checkpoints before Validation Evidence so they remain scoped to diagnostic
  evidence.
- `lab4-supervised-execution.md` guides a participant through reviewing the
  Hybrid Retrieval Agent's stored proposal, recording an explicit approval,
  running the proposal's own DDL, capturing Validation Evidence, and replaying the original
  Investigation Evidence investigation.
- `checkpoint.py` validates response files against that run's indexing receipt.

After a ready Investigation Evidence receipt, `make live-workshop` writes ready-to-edit,
run-scoped Lab 2 and Lab 3 request files under
`data/generated/incident-lab/exercises/`. Edit those generated files. The
checked-in SQL and JSON files are templates and contain no evidence
identifiers. Lab 4's guide stays in this directory because it reads the
proposal persisted by the participant's own Lab 3 run rather than a fixed
identifier.

The semantic section of the generated SQL requires one completed hybrid search
so Bedrock has persisted a query embedding. Pass that response's `run_id`:

```bash
psql "$WORKSHOP_PARTICIPANT_DATABASE_URL" -X \
  -v run_id="$RUN_ID" \
  -f data/generated/incident-lab/exercises/lab2-sql-retrieval.sql
```

The script rolls back its temporary checkpoint tables. It reads canonical
evidence and proof but does not modify either.

The Lab 3 cited-synthesis and proposal calls are real Bedrock requests. On the
August 5 Aurora PostgreSQL 18.3 `db.r8g.2xlarge` rehearsal, the combined
endpoint took 25.832 seconds wall-clock (25.338 seconds recorded answer
latency). That wait is expected: do not submit a second answer request while
the first one is grounding, persisting the cited answer, and recording its
proposal. Recalibrate the reference figure before using a different workshop
instance class.

The JSON checkpoints inspect API receipts only. They reject any candidate
outside `pg_incident_capture`, reject identifiers from another capture, and
never assert a prewritten ranking result. Labs 2 and 3 use the Investigation Evidence diagnostic
receipt: `--receipt data/generated/incident-lab/receipt-a-<suffix>.json`. Lab 4
uses the stored proposal rather than a checked-in DDL statement, then runs Validation Evidence
with `--proposal-id` and `--approved-by`. The later `validation` checkpoint takes
both Investigation Evidence and Validation Evidence receipts and requires the additive `change_validates`
relationship. The RRF SQL uses a temporary table inside a rolled-back
transaction. None of the exercises modifies canonical evidence or replaces the
source application tests.
