# Participant Exercises

These files turn Labs 2 through 4 into bounded build exercises without asking
participants to rewrite the retrieval engine or agent framework.

- `lab2-filter-request.json` returns mixed live evidence so the participant can
  add `kinds: ["change"]` and prove pre-fusion filtering.
- `lab2-fusion-request.json` carries the default weighted-RRF controls.
- `lab2-rrf.sql` contains the participant-written fusion expression and a
  fail-closed receipt checkpoint.
- `lab3-plan-request.json` asks the three-part, run-derived diagnostic question:
  backfill/write stall, pool exhaustion and recovery, then the plan regression
  that `ANALYZE` did not resolve. It distinguishes the Wave A-backed
  bounded-backfill guidance for future migrations from the post-index outcome
  that remains unavailable until Wave B.
- `lab3-traverse-request.json` and `lab3-compare-request.json` are populated
  from the current run's receipt by `make live-workshop`. Complete the Lab 2
  and Lab 3 checkpoints before Wave B so they remain scoped to diagnostic
  evidence.
- `lab4-supervised-execution.md` guides a participant through reviewing the
  Hybrid Retrieval Agent's stored proposal, recording an explicit approval,
  running the proposal's own DDL, capturing Wave B, and replaying the original
  Wave A investigation.
- `checkpoint.py` validates response files against that run's indexing receipt.

After a ready Wave A receipt, `make live-workshop` writes ready-to-edit,
run-scoped Lab 2 and Lab 3 request files under
`data/generated/incident-lab/exercises/`. Edit those generated files. The
checked-in JSON files are templates and contain no evidence identifiers. Lab
4's guide stays in this directory because it reads the proposal persisted by
the participant's own Lab 3 run rather than a fixed identifier.

The Lab 3 cited-synthesis and proposal calls are real Bedrock requests. On the
August 5 Aurora PostgreSQL 18.3 `db.r8g.2xlarge` rehearsal, the combined
endpoint took 25.832 seconds wall-clock (25.338 seconds recorded answer
latency). That wait is expected: do not submit a second answer request while
the first one is grounding, persisting the cited answer, and recording its
proposal. Recalibrate the reference figure before using a different workshop
instance class.

The JSON checkpoints inspect API receipts only. They reject any candidate
outside `pg_incident_capture`, reject identifiers from another capture, and
never assert a prewritten ranking result. Labs 2 and 3 use the Wave A diagnostic
receipt: `--receipt data/generated/incident-lab/receipt-a-<suffix>.json`. Lab 4
uses the stored proposal rather than a checked-in DDL statement, then runs Wave B
with `--proposal-id` and `--approved-by`. The later `validation` checkpoint takes
both Wave A and Wave B receipts and requires the additive `change_validates`
relationship. The RRF SQL uses a temporary table inside a rolled-back
transaction. None of the exercises modifies canonical evidence or replaces the
source application tests.
