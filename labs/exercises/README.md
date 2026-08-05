# Participant Exercises

These files turn Labs 2 and 3 into bounded build exercises without asking
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
  from the current run's receipt by `make live-workshop`.
- `checkpoint.py` validates response files against that run's indexing receipt.

`make live-workshop` writes ready-to-edit, run-scoped copies under
`data/generated/incident-lab/exercises/`. Edit those generated files. The
checked-in JSON files are templates and contain no evidence identifiers.

The Lab 3 cited-synthesis call is a real Bedrock request and normally takes
about 25 seconds. That wait is expected: do not submit a second answer request
while the first one is grounding and persisting the cited answer.

The JSON checkpoints inspect API receipts only. They reject any candidate
outside `pg_incident_capture`, reject identifiers from another capture, and
never assert a prewritten ranking result. Labs 2 and 3 use the Wave A diagnostic
receipt: `--receipt data/generated/incident-lab/receipt-a-<suffix>.json`. The
later `validation` checkpoint takes both Wave A and Wave B receipts and requires
the additive `change_validates` relationship. The RRF SQL uses a temporary table
inside a rolled-back transaction. None of the exercises modifies canonical data
or replaces the source application tests.
