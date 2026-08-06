# DAT410 Builder Session Flow

**Level:** 400
**Hard duration:** 60 minutes
**Participant outcome:** build a trustworthy, SQL-first hybrid retrieval and
proof layer from a live Aurora PostgreSQL migration failure.

The incident is the corpus generator, not the workshop outcome. Participants
turn measured signals into searchable evidence, use Aurora PostgreSQL to rank,
relate, cite, and replay that evidence, and validate a human-approved
recommendation with a second evidence wave.

> At fleet scale, telemetry is abundant; trustworthy context is scarce.

## Guide Structure

1. **Getting Started:** access the environment and verify the empty evidence
   store.
2. **Workshop Scenario:** follow one online migration through its measured
   phases and identify where each evidence signal originates.
3. **Lab 1: Capture and admit live evidence.**
4. **Lab 2: Build hybrid retrieval in SQL.**
5. **Lab 3: Build the Hybrid Retrieval Agent.**
6. **Lab 4: Validate, prove, and replay.**
7. **Take it home:** transfer the retrieval and supervised-action patterns.
8. **Summary and cleanup.**

RLS, column masking, and AgentCore transport are take-home extensions. They are
not participant-completion requirements and must not displace the core path.

## Scenario

Workshop Studio pre-provisions 5,000 customers and 3,000,000 orders in
`workbench_lab`; `casework`, `retrieval`, and `proof` start empty. The workload
is operational state, not the corpus.

In Lab 1, the participant:

1. adds a nullable `priority_tier` column and commits that DDL separately;
2. opens one unbatched backfill transaction across all orders;
3. sends 12 hot writes through the real ten-connection FastAPI pool;
4. proves 10 PostgreSQL sessions are waiting on the backfill's transaction ID
   while at least two callers wait outside PostgreSQL and return `PoolTimeout`;
5. holds that proven state long enough to observe it, commits the backfill, and
   proves the ten blocked writers drain successfully;
6. captures a named query before and after `ANALYZE`, where both checkpoints
   remain sequential scans because the composite index is absent.

The central question has three clauses:

> Why did writes time out during the priority-tier migration, why did the
> application recover after commit, and why did the priority query remain slow?

No retrieval arm answers all three. Participants must decompose, retrieve,
traverse the blocker chain, and compare plan checkpoints.

## Minimal End-to-End Path

1. Run `make live-workshop` to produce **Wave A**. It contains only diagnostic
   evidence from the backfill, lock wait, app-pool exhaustion, request
   timeouts, recovery, and pre/post-`ANALYZE` plan checkpoints.
2. Confirm the generated receipt reports a current, drift-free search index.
   The target is behavioral coverage and roughly 50-80 genuinely distinct
   documents, not padded document volume.
3. In Code Editor, exercise exact identifier, full-text, semantic, and fuzzy
   retrieval; apply filters inside each retrieval arm; edit weighted RRF; and
   inspect model reranking separately from PostgreSQL RRF.
4. Run the Hybrid Retrieval Agent against Wave A. Its cited answer explains
   the lock/pool failure, measured drain, and missing access path. It cannot
   claim a post-index result because none has been admitted.
5. Review the persisted structured proposal, citations, preconditions,
   expected effect, and rollback guidance. Explicitly approve and execute the
   rendered SQL as the participant.
6. Run `make live-workshop ARGS="--wave B --proposal-id ... --approved-by ..."`
   to record the observed index fingerprint and admit only post-index
   validation evidence.
7. Inspect the proposal, execution receipt, autonomous-readiness assessment,
   citations, relationships, and replay of the original Wave A run.

## Minute-by-Minute Run of Show

| Minute | Activity | Participant proof | Cut line |
|---:|---|---|---|
| 0-5 | Getting Started | Environment opens and evidence store is empty | Pair terminal access; do not use a prior corpus |
| 5-10 | Workshop Scenario | Distinguish operational rows from evidence and map each source to the fact it proves | No product tour |
| 10-18 | Lab 1 | Wave A receipt proves transaction-ID blocking, exhausted pool, timed-out queued callers, recovery, and two sequential plan checkpoints | Pair with a participant whose current Wave A run completed |
| 18-38 | Lab 2 | Exact, FTS, semantic, fuzzy, pre-fusion filter, weighted RRF, and rerank checks run from the current receipt | Rerank fallback is valid; preserve SQL fusion |
| 38-50 | Lab 3 | Cited diagnostic answer and structured action proposal are persisted | Use the complete answer path if individual tool calls run long |
| 50-56 | Lab 4 | Participant approval, catalog fingerprint, Wave B plan evidence, citations, and Wave A replay are visible | Preserve supervised execution and replay before visual exploration |
| 56-58 | Take it home | Explain read-only recommendation, human-approved action, and policy-bounded future autonomy | Architecture discussion only |
| 58-60 | Summary and cleanup | Workload cleanup is understood; proof remains replayable | Do not start an extension lab |

## Measured Participant Waits

The following source-path rehearsal ran on August 5, 2026 against a fresh
Aurora PostgreSQL 18.3 `db.r8g.2xlarge` test database with 3,000,000
`workbench_lab.orders` rows. These are reference measurements, not a promise
for a different Workshop Studio instance class or a cold account.

| Participant-visible action | Measured time | Facilitator line |
|---|---:|---|
| Wave A, including local workload preparation | 78.980s wall-clock, including 33.840s to prepare the workload | The pre-provisioned workshop path does not ask participants to wait for the workload build. During the capture, the controller first proves the state and then deliberately holds it for 12s. |
| Lab 3 cited answer and structured proposal | 25.832s endpoint wall-clock; 25.338s recorded answer latency | "The agent is grounding, citing, and recording a proposal. Give it about 30 seconds and do not submit a second request." |
| Participant's non-concurrent `CREATE INDEX` | 1.503s | The participant action is fast in this rehearsal; the following validation admission is the longer transition. |
| Wave B validation admission | 21.228s wall-clock | "Aurora is validating the catalog action, admitting the new evidence, and rebuilding the search index. This takes about 22 seconds in the rehearsal." |

The reference Wave A capture admitted 54 documents from 297 activity rows,
1,728 lock rows, and 270 blocker-chain rows. Wave B added three validation
documents, for 57 current documents. The corpus count is explanatory only;
behavioral coverage and the diversity gate remain the contract.

The runtime rehearsal used participant and application identities end to end.
The final release freeze still includes a visual check of the rendered frontend
surfaces on the final Workshop Studio stack.

## Provisioning Budget and Stack Lifecycle

The source-only path was measured three times on the dedicated Aurora PostgreSQL
18.3 `db.r8g.2xlarge` test target. Each clean cycle rebuilt the 3,000,000-row
operational workload and then completed Wave A:

| Cycle | Workload rebuild | Wave A | Combined |
|---|---:|---:|---:|
| 1 | 33.86s | 87.52s | 121.38s |
| 2 | 34.17s | 81.55s | 115.72s |
| 3 | 33.49s | 81.70s | 115.19s |

The 121.38-second slowest observed source path is not a full cold Workshop
Studio account measurement: it excludes Code Editor package installation,
CloudFormation resource startup, and first-account Bedrock behavior. The
Workshop Studio `BootstrapWaitCondition` is 2,400 seconds, which is 19.77 times
that observed path and therefore has ample margin. A final Workshop Studio
rehearsal must still measure its complete account bootstrap before release.

The Workshop Studio SSM bootstrap custom resource acts only on stack
**Create**. A stack **Update** acknowledges success without rerunning
`make schema` or `make prepare-workload`; use a new stack or the documented
database reset path when a fresh operational workload is required.

## Evidence and Observability Boundary

The lab uses the source with the highest fidelity for each fact:

| Fact | Authoritative lab signal |
|---|---|
| Which PostgreSQL sessions block and which PID blocks them | `pg_stat_activity`, `pg_locks`, and `pg_blocking_pids()` |
| Which callers never obtained a database connection | `psycopg_pool.get_stats()` and measured API outcomes |
| Whether the query has an access path | `EXPLAIN (ANALYZE, BUFFERS)` |
| Statement work before/during/after the incident | `pg_stat_statements` deltas |
| Supplemental RDS context | CloudWatch, when available |

Performance Insights and Database Insights are valuable production connectors
but are not core prerequisites. Their sampling and publication behavior do not
improve the causal proof required here. Production integrations can admit those
sources, APM, logs, third-party monitoring, and runbooks through the same
versioned evidence contract.

## Unique L400 Proof

1. **Relational truth and search state are different assets.** `casework.*`
   owns normalized evidence and relationships; `retrieval.*` is a derived,
   versioned, rebuildable search index.
2. **Hybrid means inspectable signals, not one opaque score.** Raw lexical,
   vector, fuzzy, RRF, and rerank values remain separate. Hybrid is evaluated,
   not presumed to win for every query.
3. **Time and schema prevent unsupported conclusions.** Lab 3 has no
   post-index evidence, so the agent cannot cite an improvement that has not
   happened.
4. **A recommendation is not an action.** The agent has no write tool or DDL
   privilege. The participant's approval, executed SQL fingerprint, Wave B
   outcome, and readiness verdict are persisted proof.

## Facilitator Gates

Before opening the room:

- Aurora PostgreSQL 18.3 and the Workshop Studio network path have passed the
  current rehearsal.
- The participant database has the 3,000,000-row operational workload and
  zero `casework`, `retrieval`, and `proof` evidence.
- The API has `LAB_ENDPOINTS_ENABLED=1` and
  `DB_POOL_MIN_SIZE=DB_POOL_MAX_SIZE=10`.
- `make doctor`, `make smoke`, the required release gates, and the frontend
  build have passed on the final source revision.
- Bedrock embedding, reranking, and synthesis access is confirmed in
  `us-east-1`.
- Wave A, participant-executed DDL, Wave B, citation validation, proposal
  fingerprint comparison, and replay have been rehearsed using the
  participant role.
- CloudWatch unavailability remains a recorded supplemental condition, not a
  participant blocker.

## Expected Outputs

- Ten connected hot writes show `Lock:transactionid` and the backfill PID;
  queued callers are proven only through pool statistics and `PoolTimeout`.
- Recovery records ten drained writes, no blocked tagged sessions, no waiting
  pool requests, and a fresh successful write.
- Wave A contains before- and after-`ANALYZE` sequential scans. `ANALYZE` is
  evidence, not an automatic fix.
- The participant-created composite index produces the Wave B index-scan
  checkpoint.
- Exact, full-text, semantic, fuzzy, filtered, fused, and reranked retrieval
  results retain their own persisted signals.
- The cited agent answer is limited to Wave A evidence and creates a structured
  proposal.
- Wave B remains additive. Replaying the Lab 3 run does not gain Wave B
  candidates, edges, or citations.
- The supervision lens distinguishes a missing proposal, pending human action,
  a mismatched execution, and a validated outcome.

## After the Session

The reusable skill is not the incident mechanism. It is the ability to convert
authoritative operational observations into versioned evidence that can be
filtered, ranked, related, cited, evaluated, and replayed before a human or
automation policy acts. At fleet scale, expand the inputs and output contract,
not the workshop's live incident surface.
