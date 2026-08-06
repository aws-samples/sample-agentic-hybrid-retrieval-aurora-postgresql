# Lab 4: Validate, Prove, and Replay

Lab 3 produced a cited proposal from Investigation Evidence. The Hybrid
Retrieval Agent can recommend an action, but it cannot execute one. This is the
**recommend, don't execute** boundary: you review the proposal and decide
whether to apply it.

## 1. Read the Stored Proposal

Use the `run_id` returned by your Lab 3 answer. The query reads the structured
proposal the answer path persisted, including its cited support and rollback
guidance.

```bash
RUN_ID=${RUN_ID:-$(jq -r '.run_id' /tmp/agent-answer.json)}
test -n "$RUN_ID"

psql "$DATABASE_URL" -X -v run_id="$RUN_ID" <<'SQL'
SELECT
  proposal_id,
  action_type,
  target_schema,
  target_table,
  key_columns,
  proposed_sql,
  preconditions,
  expected_effect,
  rollback_sql,
  rollback_guidance,
  statement_timeout,
  lock_timeout
FROM proof.action_proposals
WHERE run_id = :'run_id'::uuid
ORDER BY created_at DESC;

SELECT
  proposal_id,
  citation_number,
  claim
FROM proof.action_proposal_citations
WHERE run_id = :'run_id'::uuid
ORDER BY proposal_id, citation_number;
SQL
```

Read the proposed action, the target, the expected effect, its rollback
guidance, and the cited claims before approving anything.

## 2. Record Your Approval

Set an approval value that identifies the person or role making the decision.
Then derive the proposal ID from the same persisted Lab 3 run.

```bash
APPROVED_BY="${APPROVED_BY:?Set this to the person or role approving the proposal}"

PROPOSAL_ID="$(
  psql "$DATABASE_URL" -X -At -v run_id="$RUN_ID" <<'SQL'
SELECT proposal_id
FROM proof.action_proposals
WHERE run_id = :'run_id'::uuid
ORDER BY created_at DESC
LIMIT 1;
SQL
)"
test -n "$PROPOSAL_ID"
printf 'Approving proposal %s as %s\n' "$PROPOSAL_ID" "$APPROVED_BY"
```

The approval, the stored proposal, and the observed execution are separate
records. The next command ties them together.

## 3. Execute the Stored DDL

In Code Editor, copy the `proposed_sql` value from the proposal you just
reviewed and run it exactly as shown. Do not substitute SQL from this lab or
from another participant's run.

Wait for PostgreSQL to finish the command. Do not run the validation capture
until the command has either completed or returned an error.

## 4. Capture Validation Evidence

Run Validation Evidence with the persisted proposal ID and your explicit approval. It reads
the created index definition from Aurora's catalog, compares its canonical
fingerprint with the proposal, records the execution before admission, and then
captures the new plan evidence.

```bash
make live-workshop ARGS="--wave B --proposal-id $PROPOSAL_ID --approved-by $APPROVED_BY"
```

If the index is missing or has a different definition, Validation Evidence records that
outcome and stops before it admits validation evidence. Review the proposed and
observed fingerprints, correct the action if needed, and rerun Validation Evidence. Do not
delete the prior execution record.

## 5. Inspect What Was Proven

After a ready Validation Evidence receipt, inspect the recorded action and the two
independent readiness assessments.

```bash
psql "$DATABASE_URL" -X -v proposal_id="$PROPOSAL_ID" <<'SQL'
SELECT
  execution_id,
  approved_by,
  outcome,
  fingerprint_matches,
  observed_index_definition,
  plan_before_checkpoint,
  plan_after_checkpoint,
  wave_b_capture_id,
  wave_b_ingest_id
FROM proof.action_executions
WHERE proposal_id = :'proposal_id'::uuid
ORDER BY approved_at DESC, recorded_seq DESC;

SELECT
  pre_execution_eligible,
  pre_execution_reasons,
  post_execution_validated,
  post_execution_reasons
FROM proof.autonomy_readiness(:'proposal_id'::uuid);
SQL
```

`fingerprint_matches` reports whether PostgreSQL created the action the proposal
described. `post_execution_validated` reports what this recorded outcome proved.
`pre_execution_eligible` reports only what was knowable before execution; it
does not change because the outcome was successful. Neither result authorizes
autonomous DDL.

## 6. Replay the Original Investigation

Replay the Lab 3 run using the same `RUN_ID`. The replay remains grounded in
the evidence that existed when that run began, so its graph and citations do
not gain the post-index result from Validation Evidence.

```bash
curl -fsS "http://127.0.0.1:8000/v1/runs/${RUN_ID}" \
  > /tmp/lab4-wave-a-replay.json

jq '{
  run_id: .run.run_id,
  candidates: .run.candidate_count,
  citations: (.answer.citations | length),
  stages: (.stages | length)
}' /tmp/lab4-wave-a-replay.json
```
