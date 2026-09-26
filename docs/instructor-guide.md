# Instructor guide

## Pre-session checklist

Aurora only. There is no local database and no `make` target creates one. See
`ARTIFACTS.md`, including how to connect from a corporate network.

- confirm the base bootstrap with `make db-verify-bootstrap`, and the real
  catalog's 553,911 products and vectors through the restore's verification;
- save `build/bootstrap-timings.tsv`; report the measured `index_creation` and
  `total` rows rather than estimating them;
- run `MISSION_GATE_REQUIRE_DB=1 make validate-missions`;
- run `make validate-evals`;
- run `make validate-config`;
- run `FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions`;
- execute the eval harness and save a named baseline;
- run the HNSW matrix on the exact Aurora configuration used in the room;
- verify the three starter gaps, source revision, and Claude Code model from a
  fresh Workshop Studio deployment, and record that rehearsal with
  `scripts/rehearsal.py` rather than loose command output — see
  [`docs/rehearsal-runbook.md`](rehearsal-runbook.md) for the full clean-account
  sequence and its evidence manifest; deployment, transfer, bootstrap, index,
  reranker, and agent timing belong in that manifest, not in this guide, so a
  stale number here can never disagree with what was actually measured;
- run `pytest -q tests/test_lab_state.py` so reset, solution, and isolation are
  byte-stable when repeated;
- run one configured-model rehearsal with
  `uv run python scripts/benchmark_ask_mosaic.py --agent-model
  global.anthropic.claude-sonnet-5 --synthesis-model
  global.anthropic.claude-sonnet-5 --runs 1 --full-runs 1`; this warms the
  real retrieval, rerank, agent, and synthesis path;
- validate the expected room concurrency against the account's Bedrock quotas
  and the API pool with `scripts/load_exercise.py` (see
  [`docs/rehearsal-runbook.md`](rehearsal-runbook.md#bounded-concurrency-exercise)),
  run once cold and once warm. Do not discover a quota limit from participant
  traffic, and do not print a latency or concurrency figure here that the
  exercise's own recorded report does not carry.

Rehearse against `reviews-2023-v2`. The prepared Aurora catalog has
553,911 imported records and vectors. Read `/api/readiness` and confirm both
API and terminal select that dataset. Live development checks do not prove
that the published Workshop Studio bootstrap loads this new dataset. Complete
the delivery-asset migration and fresh-environment rehearsal before the event.
The historical synthetic scorecard and 720 filter cases are not its quality gate.

## 60-minute path

| Clock | Stage | Required outcome |
|---|---|---|
| 00:00-00:10 | Introduction / Overview / Presentation | Meet Alex, frame the three lessons and explain the architecture |
| 00:10-00:20 | Retrieve | Restore one candidate channel and prove recall and eligibility |
| 00:20-00:30 | Rank | Repair RRF so the suitable monitor reaches reranking |
| 00:30-00:50 | Reason | Attach evidence identity to synthesis state, prove citation authorization and run the completion gate |
| 00:50-01:00 | Flex | Build a retrieval tool by default, with HNSW as the fallback |

## Eight proof anchors

Participants issue three before-and-after requests. Five additional anchors run
inside the production validators:

| Stage | Run | Proof |
|---|---|---|
| Retrieve | `G-003` | In this measured request, neither FTS nor the bounded semantic pool contains the target; restoring the trigram channel recovers it |
| Retrieve | `G-001` | Correct listing ID remains first with an exact-term match |
| Retrieve | `G-012` | Every saved product satisfies the Bose brand and headphones category |
| Rank | `G-008` | RRF moves from rank-collapsing arithmetic to `1 / (k + source_rank)` |
| Rank | `G-007` | Dell U2720Q and SE2717H provide an explicit 4K-versus-1080p comparison |
| Rank | `G-009` | Dell brand and monitor category remain pre-ranking requirements |
| Reason | `G-021` | Evidence plumbing moves a fail-closed response to a grounded cited comparison |
| Reason | `G-019` | Bose specification and sampled review claims resolve to separate source records |

The query text, filters, targets, bad observation, good observation, and
participant edit are owned by `data/evals/mosaic_labs_missions.json`. Workshop
Studio renders the three required requests, names all five controls, and checks
every rendered payload for drift.

## Teaching narrative

Use the role-based opening and expert discussion cues in
[`workshop.md`](../workshop.md). The participant guide's shape, graded work and
pacing are recorded in the [L400 lab design](l400-lab-design.md); the payloads,
repairs and validation sequence are unchanged by it.

### Repeatable delivery loop

For each lab, keep the canonical query, filters and runtime profile fixed. Ask
for a prediction, run the broken request, inspect the recorded mechanism, apply
the smallest repair, and run that identical request again. Record the request
and run ID in both states. A changed prompt or an unrelated result that looks
better cannot establish that the repair worked.

Use the [lab regression release sequence](lab-golden-queries.md) for
reset, apply, validation and recovery. `make lab-status` inspects source files;
it does not prove the running API or Aurora has loaded them. The validators
check the installed SQL and production responses. The browser's Lab 3 proof
does not run the separate evidence-grounding control; the terminal validator
remains the completion gate.

### Opening

"We have provided the catalog, embeddings and application scaffolding. You will
implement three critical connections and prove what changed. Retrieve asks
whether the right eligible candidates entered the pool. Rank asks whether that
pool was combined correctly. Reason asks which sources support the choice."

Point the room at the Playground before narrating any of it: opening
`/labs/retrieval` with no saved Shop search leads with a "Required workshop
path" panel naming the three labs in order, each one's live repair state, and
one button into whichever lab still needs it. Say once that this panel, not the
storefront or the Scale & HNSW / Session & Memory links beside it, is the
session, and move on -- the panel keeps saying so for the rest of the hour, and
a participant who reopens the tab lands on it again rather than back at Lab 1.

Show the missed product first and collect a prediction. Leave the disconnected
path and its repair for Lab 1's diagnosis.

### Lab 1 - Build hybrid retrieval

FTS is strong when words and identifiers exist. `pg_trgm` recovers nearby
strings. HNSW expands semantic intent. SQL predicates and JSONB filters decide
eligibility inside every candidate arm.

The request transposes two adjacent characters in a real listing ID. The
bounded meaning search returns plausible headphones without that listing.
Restoring `pg_trgm` admits Bose QuietComfort 35 II. Show both identifiers and
ask why other listings are wrong for an identity request; do not imply
that other headphones lack noise cancellation.

The exact-ID control proves FTS still works. G-012 uses a full-word Bose need
with brand/category filters. Inspect both served rows and the complete saved
pool. An approximate vector scan can obey every SQL filter and still miss
qualifying rows; candidate count and eligibility are different checks.

### Lab 2 - Fuse, rerank, and inspect

RRF combines independent rank positions without pretending raw FTS, trigram,
and vector scores share a scale. Cohere Rerank operates on the bounded fused
pool. It does not replace retrieval or override deterministic eligibility.

Ask attendees to compare per-arm rank, contribution, fused rank, and final rank
for the top two results. The line to land is: "A correct answer is not proof of
a correct pipeline." Historical weighted fusion is optional.

Before repair, the monitor request drops the ViewSonic VG2756-4K before
reranking; the collapsed formula fills the pool by product id, so a Dell
U2720Q relisting leads the broken shortlist and a 1440p Lenovo ThinkVision
T27hv-20 still occupies a slot for a 4K request. Inspect a source position
greater than 1: the broken formula gives it rank-1 credit. After repair, the
ViewSonic enters the combined list at position 21 and reaches final position
5; read the participant's actual value.

Other feature requests retain their first result through the same faulty
formula. Use those as controls, not as visible repair demonstrations. The
[example library](real-catalog-exercise-library.md) includes successes,
unchanged results and an unsuccessful wording variant.

### Lab 3 - Build and deploy an agent

Participants extend their SQL from Labs 1 and 2. They list the Gateway tools,
complete `create_agent` in `labs/lab3/agent.py`, add one source-aware instruction,
and run `make deploy-agent`. The managed services and networking are prepared.

Show the deployment message, then ask the ViewSonic monitor and Steelcase Gesture
question in Playground → Reason. Open a citation and compare the claim with its
source. Follow up in Ask Mosaic with a 100W laptop-charging requirement; the
monitor's 90W record must not be presented as meeting 100W.

Participants build and use the agent. They do not write tests or a claims query.
The completion command `make complete-lab-3 RUN_ID=...` rechecks the actual run,
its deployed source and its SQL searches without another model invocation.


### Advanced Labs (OPTIONAL)

HNSW quality is workload-specific. The required path proves candidate inclusion and eligibility. The optional plan inspection reads the existing index. Recall/latency tuning remains optional rather than becoming a
rushed fourth lab.

After Lab 3, name the deployed boundaries: Aurora runs retrieval and stores
evidence; Strands chooses tools; AgentCore Runtime hosts the agent and SQL tool
service; Gateway exposes those tools over MCP; Memory supplies conversation
context. Product facts still come from Aurora.

## Failure-safe sequence

1. If the environment is delayed, inspect the asset download, cache verification,
   catalog load, and index-build timings before changing the bootstrap contract.
2. If cache access, KMS access, Aurora connectivity, or a required Bedrock
   model is unavailable, stop the affected exercise and escalate the environment
   issue. Do not switch to fixtures or a local database.
3. Catalog inspection remains available when model access is unavailable, but
   model-dependent retrieval must report failure rather than fabricate results.
4. To show an expected state during an outage, replay it from the instructor's
   own rehearsal output. Nothing the instructor shows counts as evidence that
   a participant check passed. Incident and fallback screenshots are retired
   workshop assets; do not reintroduce them.
5. If `psql` hangs while the port is reachable, inspect TLS settings before the
   security group. See `ARTIFACTS.md`.

## Suggested audience questions

- Which query failures require lexical, fuzzy, or semantic retrieval?
- Which constraints must never be delegated to a reranker?
- Why did result 1 outrank result 2 before and after reranking?
- What evidence should an agent retain for a recommendation?
- How much Recall@K would you trade for p95 latency in this workload?

## Carry the story and reuse the proof

Discover’s third need is more screen space, matching the presentation and Shop's monitor example. Lab 3 brings the monitor and chair decisions together: carry forward the monitor requirements from Lab 2 and gather separate evidence for each item. The monitor is also an exact-model control and an optional HNSW example. The SQL repairs feed the deployed agent; the mission and evidence checks cover the monitor's size, resolution, USB-C video and charging.

Ask each checkpoint question before the SQL repair. In Lab 3, show the monitor
and chair searches and open one source. Distinguish a deployment failure from a
working answer that declines an unsupported claim.

At completion, use the participant's run ID:

```sh
make complete-lab-3 RUN_ID=<run-id>
```

The receipt binds the deployed code and current settings. It is regraded from
Aurora; a facilitator demonstration does not complete a participant's exercise.

Default the ten-minute flex block to [Build a retrieval tool](build-retrieval-tool.md). Its four hints preserve the final two-budget proof and agent call. HNSW is the fallback. Use [the delivery map](abstract-delivery-map.md) to distinguish what attendees implement from what they inspect.
