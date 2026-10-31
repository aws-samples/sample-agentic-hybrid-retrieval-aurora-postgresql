# Historical measurements

`canonical_scorecard.json` and `canonical_stage_ablation.json` were measured
again on 31 October 2026, after the searches were renamed to match the session
abstract (full-text search `fts`, pg_trgm fuzzy matching `fuzzy`, pgvector
semantic search `semantic`). Every metric equals the previous measurement; the
earlier records stay in Git history with their original labels and hashes.

Two held-out measurements keep the names they were measured under, because
re-running them is a new experiment, not a rename:

- `esci_k_sweep.json` (26 September 2026) lists its limits as `fts`, `trigram`
  and `semantic`; `trigram` is today's `fuzzy`.
- `hybrid_payoff.json` (3 October 2026, 399 queries) names its arms
  `vector_embed_v4`, `vector_small` and similar; `vector` is today's `semantic`.
  The DAT410 deck's held-out chart quotes it.

Before 31 October the scorecard and ablation were retained in place as historical
records, with their original measurements, query labels, source hashes and model
metadata. They were not results for the revised monitor exercises.

On 20 September 2026, G-007 changed to a monitor comparison and G-021 changed
to a monitor-and-chair agent request. The mission manifest and canonical
judgments describe those current cases. Reusing an earlier measurement against
the changed cases would misattribute its scores.

The API compares the measurement's retrieval, query, model and methodology
identity with the running application. The UI withholds stale quality metrics
under **Historical test results**. The participant's **Complete the workshop**
checks run independently against their actual repairs and current Aurora
records. A historical PASS count cannot complete a lab.

For release, review the query set against the chosen catalog and make fresh
measurements with `scripts/score_evals.py --write-baseline` and
`scripts/ablation_evals.py`. Preserve the old records in Git history; do not
change their hashes or labels to make them appear current.
