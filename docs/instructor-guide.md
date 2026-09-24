# Instructor guide

## Pre-session checklist

Aurora only. There is no local database and no `make` target creates one. See
`ARTIFACTS.md`, including how to connect from a corporate network.

- confirm the base bootstrap with `make db-verify-bootstrap`, and the real
  catalog's 500,000 products and vectors through the restore's verification;
- save `build/bootstrap-timings.tsv`; report the measured `index_creation` and
  `total` rows rather than estimating them;
- run `MISSION_GATE_REQUIRE_DB=1 make validate-missions`;
- run `make validate-evals`;
- run `make validate-config`;
- run `FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions`;
- execute the eval harness and save a named baseline;
- run the HNSW matrix on the exact Aurora configuration used in the room;
- verify the three starter gaps, source revision, and Claude Code model from a
  fresh Workshop Studio deployment, and keep that rehearsal's command output
  for reference during delivery;
- run `pytest -q tests/test_lab_state.py` so reset, solution, and isolation are
  byte-stable when repeated;
- run one configured-model rehearsal with
  `uv run python scripts/benchmark_ask_mosaic.py --agent-model
  global.anthropic.claude-sonnet-5 --synthesis-model
  global.anthropic.claude-sonnet-5 --runs 1 --full-runs 1`; this warms the
  real retrieval, rerank, agent, and synthesis path;
- validate the expected room concurrency against the account's Bedrock quotas
  and the API pool. Do not discover a quota limit from participant traffic.

Rehearse against `reviews-2023-500k-v1`. The prepared Aurora catalog has
500,000 imported records and vectors. Read `/api/readiness` and confirm both
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
[`workshop.md`](../workshop.md). The participant guide's shape is recorded in
the [lab exercise design](superpowers/specs/2026-09-19-lab-exercise-design.md);
the payloads, repairs and validation sequence are unchanged by it.

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

Before repair, the monitor request drops Dell U2720Q before reranking;
HP Z27n's visible 1440p specification conflicts with 4K. Inspect a source
position greater than 1: the broken formula gives it rank-1 credit. After
repair, the Dell enters the combined list and is reranked first. Its combined
position was 24 in repeated verification; read the participant's actual value.

Other feature requests retain their first result through the same faulty
formula. Use those as controls, not as visible repair demonstrations. The
[example library](real-catalog-exercise-library.md) includes successes,
unchanged results and an unsuccessful wording variant.

### Lab 3 - Build the retrieval agent

The agent receives typed, read-only retrieval tools. The model requests an
operation; application code decides whether it executes. Evidence returned to
the model is not citable until the application registers its identity for the
retrieved product. The broken HTTP 503 is therefore the correct fail-closed
outcome, not an outage to work around.

Make the handoff visible: evidence returned by `get_product_evidence` must enter
both the evidence-ID map and the product's evidence-ID list. After the repair,
restart the API and start a new run. Read one citation's product, source revision
and supporting text; a resolved ID establishes identity, while the text must
still support the claim. Do not bypass authorization or loosen grounding to
turn the expected refusal into HTTP 200.

Then ask what the cited words actually establish. Compare a specification with
a review when both are available, and name any unsupported requirement. The
Playground activity log distinguishes model-requested steps from steps started
by the application; older records may lack that origin. Count only recorded
actions, and distinguish failed or declined steps from successful ones.

The implementation is one bounded Strands agent, not a multi-agent or multi-hop
system. Closed-world follow-ups may inspect a server-authorized prior shortlist,
but fresh evidence and citation validation are required for every answer.

### Advanced Labs (OPTIONAL)

HNSW quality is workload-specific. The required path proves candidate inclusion and eligibility. The optional plan inspection reads the existing index. Recall/latency tuning remains optional rather than becoming a
rushed fourth lab.

After Lab 3, show contract portability in under a minute. No AgentCore resource
is deployed and no Gateway runtime parity is claimed. State the ownership
boundary: Aurora owns retrieval truth, Bedrock models provide intelligence, the
application owns execution and citation authority, and AgentCore can provide a
managed runtime or tool transport without taking over retrieval.

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

Discover’s third need is more screen space, matching the presentation and Shop's monitor example. Lab 3 brings the monitor and chair decisions together: carry forward the monitor requirements from Lab 2 and gather separate evidence for each item. The monitor is also an exact-model control and an optional HNSW example. The three repair seams remain unchanged; the mission and evidence checks cover the monitor's size, resolution, USB-C video and charging.

Ask each checkpoint question before repair. Lab 3 should explicitly show the monitor and chair searches in `plan`, explain that the prompt names their taxonomy, and separate HTTP 503 failure from a successful answer that declines unsupported claims.

At the end of Lab 3, save the validator's receipt:

```sh
uv run python scripts/validate_lab.py --lab 3 \
  --save-receipt .local/lab-3-validation.json
```

Pass `--api-url` if the API is not at the script's default endpoint. The
completion gate can use `--reuse-receipt` with that same file: it binds the
source and settings, reopens both Aurora agent runs and resolves their evidence
again. It saves two model invocations without accepting a cached verdict or a
facilitator's demonstration as completion. A source or settings mismatch
requires fresh validation.

Default the ten-minute flex block to [Build a retrieval tool](build-retrieval-tool.md). Its four hints preserve the final two-budget proof and agent call. HNSW is the fallback. Use [the delivery map](abstract-delivery-map.md) to distinguish what attendees implement from what they inspect.
