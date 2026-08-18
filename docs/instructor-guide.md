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
  for reference during delivery.

## 60-minute path

| Clock | Stage | Required outcome |
|---|---|---|
| 00:00-00:08 | Getting started | Open both participant surfaces, establish Mosaic, and show the baseline failure |
| 00:08-00:22 | Retrieve | Restore trigram fusion, preserve exact identity, enforce eligibility, and inspect candidate provenance |
| 00:22-00:37 | Rank | Repair RRF, inspect reranking evidence, and explain why result 1 outranked result 2 |
| 00:37-00:53 | Reason | Attach retrieved evidence to synthesis, inspect tool receipts, and produce a cited recommendation |
| 00:53-00:58 | Wrap-up | Run the scorecard and recap the architecture |
| 00:58-01:00 | Recovery buffer | Absorb a transition or rerun the failed checkpoint without shortening the required work |

## Eight participant runs

The runs are checkpoints inside three labs, not eight mini-labs:

| Stage | Run | Proof |
|---|---|---|
| Retrieve | `G-003` | The typo target moves from absent to recovered with trigram provenance |
| Retrieve | `G-001` | Exact visible model name remains in the top three with FTS provenance |
| Retrieve | `G-013` | The eligible carbon racer remains and the refurbished sibling is excluded |
| Rank | `G-008` | RRF moves from rank-collapsing arithmetic to `1 / (k + source_rank)` |
| Rank | `G-007` | Mechanical and cheaper keyboard alternatives retain inspectable rank movement |
| Rank | `G-009` | Price and headrest constraints remain pre-ranking gates |
| Reason | `G-010` | Evidence plumbing moves a fail-closed response to a grounded cited comparison |
| Reason | `G-020` | The 12-hour chair claim resolves to real evidence records |

The query text, filters, targets, bad observation, good observation, and
participant edit are owned by `data/evals/mosaic_labs_missions.json`. Workshop
Studio renders those same requests and its parity script checks for drift.

## Teaching narrative

### Opening

"Product search is where retrieval techniques stop being interchangeable. A
shopper can misspell a model, describe a benefit instead of a feature, require a
hard compatibility constraint, and still expect an explainable answer."

### Lab 1 - Build hybrid retrieval

FTS is strong when words and identifiers exist. `pg_trgm` recovers nearby
strings. HNSW expands semantic intent. SQL predicates and JSONB filters decide
eligibility inside every candidate arm.

Measured on the all-misspelled checkpoint, the semantic arm returns a full
plausible pool without the target. Do not claim embeddings recovered the typo.
The checkpoint proves that different retrieval channels solve different failure
modes and that the Lab 1 objective is candidate quality, not the final winner.

### Lab 2 - Fuse, rerank, and inspect

RRF combines independent rank positions without pretending raw FTS, trigram,
and vector scores share a scale. Cohere Rerank operates on the bounded fused
pool. It does not replace retrieval or override deterministic eligibility.

The historical weighted comparison reorders 243 of 250 candidates for the lab
anchor while reranking can absorb the difference. Ask attendees to compare
pre-rerank and final positions for the top two results and explain the change
using persisted rank evidence.

### Lab 3 - Build the retrieval agent

The agent receives typed, read-only retrieval tools. It decomposes the compound
request, performs targeted searches, retrieves evidence, compares candidates,
and produces a source-revisioned cited answer. If retrieval is unavailable, it
reports the gap instead of answering from model memory.

### Advanced Labs (OPTIONAL)

HNSW quality is workload-specific. An honest operating point needs measured
recall, latency, plans, filters, and configuration, so it remains optional
rather than becoming a rushed fourth required lab.

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
