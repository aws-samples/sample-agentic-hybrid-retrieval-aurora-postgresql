# Participant Exercises

These files turn Labs 2 and 3 into bounded build exercises without asking
participants to rewrite the retrieval engine or agent framework.

- `lab2-filter-request.json` starts with an intentionally unscoped query.
- `lab2-fusion-request.json` carries the default weighted-RRF controls.
- `lab2-rrf.sql` contains the participant-written fusion expression and a
  fail-closed receipt checkpoint.
- `lab3-plan-request.json` asks the canonical incident question.
- `lab3-traverse-request.json` and `lab3-compare-request.json` contain values
  the participant must replace after reading the decomposition.
- `checkpoint.py` validates response files produced by the workshop API.

Copy the JSON files into a scratch `participant/` directory before editing
them. The checked-in files remain the recovery state.

The JSON checkpoints inspect API receipts only. The RRF SQL uses a temporary
table inside a rolled-back transaction. None of the exercises modifies
canonical data, calls a model through the checkpoint, or replaces the source
application tests.
