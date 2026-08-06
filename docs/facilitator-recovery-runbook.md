# Facilitator Recovery Runbook

Use this guide only with the disposable workshop database. The participant
database begins with an empty evidence store and one pre-provisioned
`workbench_lab` workload. Never copy evidence, receipts, or generated payloads
between participants.

## First Check

Run the following before deciding whether intervention is needed:

```bash
make doctor
```

`doctor` distinguishes an empty database awaiting Investigation Evidence from a ready Investigation Evidence
or Validation Evidence corpus. A CloudWatch warning is not a reason to restart the lab.

## Investigation Evidence Does Not Prove The Hold

**Symptom**

The runner stops with a message such as:

```text
only 7 of 10 tagged sessions were ever blocked on the backfill
```

**Meaning**

The controller never observed all ten application-pool connections blocked on
the backfill transaction. It did not admit evidence.

**Recovery**

Restore the standard 12 hot-write requests, then rerun Investigation Evidence:

```bash
unset LAB_HOT_WRITE_REQUEST_COUNT
make live-workshop
```

If a killed process or a local experiment left the lab workload uncertain, run
`make prepare-workload` first. It rebuilds the disposable operational schema
only when the evidence store is empty.

## Orchestrator Is Interrupted During The Hold

**Symptom**

The terminal closes or the orchestration process is killed during the observed
lock-wait state.

**Recovery**

Rebuild the unadmitted workload, then verify the API pool recovered:

```bash
make prepare-workload
curl -fsS http://127.0.0.1:8000/v1/lab/pool-status
make doctor
```

The expected clean pool result has all ten connections available and no waiting
requests. Do not terminate unrelated database sessions. The controller and
workload reset target only the tagged lab sessions and `workbench_lab`.

## CloudWatch Is Unavailable

**Symptom**

Investigation Evidence completes with:

```json
{"cloudwatch_status":"unavailable"}
```

**Meaning**

CloudWatch did not return supplemental RDS metrics during the capture window.
PostgreSQL activity, locks, blocking chains, pool statistics, request outcomes,
WAL, and plans remain the core evidence.

**Recovery**

None. Continue with the Investigation Evidence receipt. Do not block or rerun the workshop
solely to obtain CloudWatch data.

## Validation Evidence Starts Without Investigation Evidence

**Symptom**

```text
Validation Evidence requires Lab 1's admitted Investigation Evidence; run Lab 1 first
```

**Recovery**

Run Investigation Evidence, build the cited canonical agent answer, review its proposal, and
then run Validation Evidence with that proposal ID. Validation Evidence has no standalone incident
meaning.

## Participant Index Is Missing

**Symptom**

```text
no participant-created index was found. The failed execution is recorded;
correct the DDL and rerun Validation Evidence.
```

**Meaning**

The attempted approval is preserved as an append-only failed execution. No Wave
B evidence was admitted.

**Recovery**

Read the stored `proposed_sql`, run it in Code Editor as the participant, and
rerun the same Validation Evidence command. Do not delete the failed execution record.

## Participant Index Does Not Match The Proposal

**Symptom**

```text
the participant-created index does not match the approved proposal
```

The supervision view shows `fingerprint_matches = false`; the mismatch is
recorded and Validation Evidence is not admitted.

**Recovery**

Compare the proposed SQL and the catalog definition, remove the incorrectly
shaped disposable-lab index as the participant, run the stored proposal
exactly, and rerun Validation Evidence:

```bash
psql "$WORKSHOP_PARTICIPANT_DATABASE_URL" -X \
  -c "DROP INDEX IF EXISTS workbench_lab.<incorrect_index_name>"

make live-workshop ARGS="--wave B --proposal-id $PROPOSAL_ID --approved-by $APPROVED_BY"
```

The expected index keys are `priority_tier` followed by `created_at DESC`.

## Validation Evidence Or DDL Is Repeated

**Symptom**

Running the stored DDL again returns:

```text
relation "idx_orders_priority_tier_created_at" already exists
```

Rerunning Validation Evidence returns an `idempotent_replay: true` admission receipt and
does not add documents or embeddings.

**Recovery**

Do not recreate or drop a matching index. The first ready Validation Evidence capture is
already valid. A repeated Validation Evidence run is safe and records a separate,
append-only observation of the same catalog state.

## A Strands Answer Has No Proposal

**Symptom**

`POST /v1/agent/strands/answer` returns `200`, but its supervision view says
`No proposal recorded for this run`.

**Meaning**

The model-selected tools produced a cited answer, but the supervised-action
proposal is intentionally persisted only by the canonical
`POST /v1/agent/answer` path.

**Recovery**

This is expected. Use the canonical answer endpoint for Lab 3 when the group
needs a persisted proposal for Lab 4. Do not insert a proposal manually.

## DDL Is Attempted Through The API Identity

**Symptom**

The application identity can update `workbench_lab.orders`, but receives
permission errors for `CREATE INDEX`, `DROP TABLE`, `TRUNCATE`, and direct
writes to `proof.action_executions`.

**Recovery**

This is the expected separation of duties. Run the proposal's DDL in Code
Editor as `workshop_participant`; let the owner-side Validation Evidence recorder capture
the human approval and observed catalog result. The Hybrid Retrieval Agent has
no database login, write tool, or DDL privilege.

## Preserve The Evidence Boundary

Do not use a previous participant's receipt, generated JSON, embedding cache,
or retrieval corpus as a shortcut. If an Investigation Evidence admission has not completed,
repair the disposable operational workload and reproduce the participant's own
incident. If Investigation Evidence is already admitted, preserve it and repair only the
participant action before retrying Validation Evidence.
