# Historical measurements

The saved `canonical_scorecard.json` and `canonical_stage_ablation.json` are
retained in place as historical records. Their original measurements, query
labels, source hashes and model metadata are preserved. They are not results
for the revised monitor exercises or the incoming public catalog.

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
