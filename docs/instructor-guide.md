# Instructor guide

## Pre-session checklist

Aurora only. There is no local database and no `make` target creates one. See
`ARTIFACTS.md`, including how to connect from a corporate network.

- confirm the asset-backed bootstrap produced 500,000 products and full
  embedding coverage with `make db-verify-bootstrap`;
- save `build/embedding-cache-download-timing.tsv` and
  `build/bootstrap-timings.tsv`; report the measured `index_creation` and
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
  global.anthropic.claude-sonnet-4-6 --synthesis-model
  global.anthropic.claude-sonnet-4-6 --runs 1 --full-runs 1`; this warms the
  real retrieval, rerank, agent, and synthesis path;
- validate the expected room concurrency against the account's Bedrock quotas
  and the API pool. Do not discover a quota limit from participant traffic.

## 60-minute path

| Clock | Stage | Required outcome |
|---|---|---|
| 00:00-00:10 | Getting started | Frame the pipeline thesis, open both participant surfaces, and capture the baseline failure |
| 00:10-00:20 | Retrieve | Restore one candidate channel and prove recall, eligibility, and the HNSW plan |
| 00:20-00:30 | Rank | Repair RRF and prove why reranking hid the broken fused order |
| 00:30-00:45 | Reason | Attach evidence identity to synthesis state and prove citation authorization |
| 00:45-00:50 | Wrap-up | Run the completion gate and separate regression, quality, and contract evaluation |
| 00:50-01:00 | Flex | Use one optional lab, recover a table, or take questions |

## Eight proof anchors

Participants issue three before-and-after requests. Five additional anchors run
inside the production validators:

| Stage | Run | Proof |
|---|---|---|
| Retrieve | `G-003` | The target remains visible through incidental FTS while missing trigram provenance returns |
| Retrieve | `G-001` | Exact visible model name remains first with FTS provenance |
| Retrieve | `G-013` | The eligible carbon racer remains and the refurbished sibling is excluded |
| Rank | `G-008` | RRF moves from rank-collapsing arithmetic to `1 / (k + source_rank)` |
| Rank | `G-007` | Mechanical and cheaper keyboard alternatives retain inspectable rank movement |
| Rank | `G-009` | Price and headrest constraints remain pre-ranking gates |
| Reason | `G-010` | Evidence plumbing moves a fail-closed response to a grounded cited comparison |
| Reason | `G-020` | The 12-hour chair claim resolves to real evidence records |

The query text, filters, targets, bad observation, good observation, and
participant edit are owned by `data/evals/mosaic_labs_missions.json`. Workshop
Studio renders the three required requests, names all five controls, and checks
every rendered payload for drift.

## Teaching narrative

### Opening

"Retrieval correctness is a pipeline property, not a top-1 result. Retrieve asks
whether the right eligible candidates entered the pool. Rank asks whether that
pool was combined correctly. Reason asks whether synthesis used only evidence
the application authorized."

### Lab 1 - Build hybrid retrieval

FTS is strong when words and identifiers exist. `pg_trgm` recovers nearby
strings. HNSW expands semantic intent. SQL predicates and JSONB filters decide
eligibility inside every candidate arm.

Measured on the all-misspelled checkpoint, the semantic arm returns a full
plausible pool without the target. Do not claim embeddings recovered the typo.
The checkpoint proves that different retrieval channels solve different failure
modes and that the Lab 1 objective is candidate recall, not the final winner.
Ask explicitly: "Why is seeing product 2 not enough to declare retrieval
healthy?" Keep the required HNSW plan check to 60-90 seconds and do not rebuild
an index.

### Lab 2 - Fuse, rerank, and inspect

RRF combines independent rank positions without pretending raw FTS, trigram,
and vector scores share a scale. Cohere Rerank operates on the bounded fused
pool. It does not replace retrieval or override deterministic eligibility.

Ask attendees to compare per-arm rank, contribution, fused rank, and final rank
for the top two results. The line to land is: "A correct answer is not proof of
a correct pipeline." Historical weighted fusion is optional.

### Lab 3 - Build the retrieval agent

The agent receives typed, read-only retrieval tools. The model requests an
operation; application code decides whether it executes. Evidence returned to
the model is not citable until the application registers its identity for the
retrieved product. The broken HTTP 503 is therefore the correct fail-closed
outcome, not an outage to work around.

The implementation is one bounded Strands agent, not a multi-agent or multi-hop
system. Closed-world follow-ups may inspect a server-authorized prior shortlist,
but fresh evidence and citation validation are required for every answer.

### Advanced Labs (OPTIONAL)

HNSW quality is workload-specific. The required path proves one index plan and
bounded pool. Recall/latency tuning remains optional rather than becoming a
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
