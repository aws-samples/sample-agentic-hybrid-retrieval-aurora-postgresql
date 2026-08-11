# Instructor guide

## Pre-session checklist

Aurora only — there is no local database and no `make` target creates one. See
`ARTIFACTS.md`, including how to connect from a corporate network.

- `make db-bootstrap-cached` — schema, catalog, cached embeddings, indexes, and
  the premium cohort, in order
- confirm 500,000 products and full embedding coverage: `make db-smoke`
- **run the three gates**, which is what proves the session can actually run:
  - `MISSION_GATE_REQUIRE_DB=1 make validate-missions` — every mission target
    resolves and satisfies its own filters on *this* cluster
  - `make validate-config` — retrieval numbers declared in exactly one place
  - `FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions` — no superseded
    function signature left callable
- execute the eval harness and save a named baseline
- run the HNSW matrix on the exact Aurora configuration used in the room
- replace all sample UI performance values with measured or clearly projected data
- prewarm the most important paths, but retain one cold-cache comparison if teaching it
- verify fallback screenshots and instructor result files

## Narrative

### Opening

“Product search is where retrieval techniques stop being interchangeable. A user can misspell a model, describe a benefit instead of a feature, require a hard compatibility constraint, and still expect an explainable answer in milliseconds.”

### `typo-recovery` takeaway (11 min)

FTS is excellent at words that exist. `pg_trgm` is excellent at recovering nearby
strings. Neither understands purchase intent by itself.

Measured, and worth saying out loud: on this query every token is misspelled, and
the **semantic arm does not recall the target at all** — it returns a full 150-row
pool of plausible headphones, none of them the answer. FTS and trigram each rank it
first. Embeddings do not recover typos, which is why this mission does not claim
the vector arm.

### `rank-with-evidence` takeaway (12 min)

Vectors understand intent, but similarity does not prove eligibility — and
eligibility is a **gate, not a re-ranking**: `matches_filters` runs inside each
arm, so an ineligible product is never a candidate in the first place.

RRF then lets independently useful rankers cooperate without pretending their raw
scores share a scale. Reranking operates on a bounded pool and handles nuanced
relevance and hard negatives.

The B-side runs the same candidate pool through weighted fusion with historical,
pre-rewrite coefficients that were never tuned for this corpus. Measured: the
weights reorder 243 of 250 candidates while **every assertion holds unchanged**,
because the reranker absorbs the difference. Fusion is highly sensitive to
coefficients and the answer layer is not — measure both before adopting either.
With rerank *off* the absorption disappears and fusion order is load-bearing.

### `agentic-research` takeaway (11 min)

A bounded, read-only typed tool is what makes an answer checkable. The agent
cites catalog evidence with source revisions, and when a tool is missing it
reports the gap instead of answering from model memory.

### Self-paced: `hnsw-performance` takeaway

HNSW quality is workload-specific. Measure recall against exact search, measure
latency under realistic filters and concurrency, and preserve the full
configuration with every result.

This is deliberately **off the timed clock**: an honest number needs a benchmark
run, and a four-minute demo would teach guessing. The scorecard points at it —
the operating point is measured, not guessed, and the self-paced lane measures it
on your own cluster.

## Failure-safe sequence

1. If the catalog load is delayed, restore from the **cluster snapshot** — that is
   the only restore path. The "balanced 5K database" fallback that used to sit
   here required a local PostgreSQL, which no longer exists (`ARTIFACTS.md`).
   `data/sample/products_5000.csv.gz` still ships, but as generator fixtures, not
   as a retrieval substrate.
2. Catalog and product inspection remain available when model access is
   unavailable; model-dependent retrieval must report the failure rather than
   fabricate results.
3. A saved measured benchmark result can populate the HNSW UI.
4. Scale projections are visibly labeled and never substituted for measured
   results without disclosure.
5. If `psql` hangs while the port looks open, it is TLS rather than the firewall.
   Run `sslmode=disable` to confirm, then add `sslnegotiation=direct`. Do not
   spend room time on the security group first.

The UI does not fall back to static product JSON when the API is unavailable.
Use instructor screenshots only as presentation backup, never as workshop
retrieval evidence.

## Suggested audience questions

- Which queries are impossible to solve reliably with keyword search alone?
- Which constraints must never be left to a reranker?
- What should happen when inventory freshness conflicts across sources?
- When would a partial HNSW index or partition be justified?
- How much recall would you trade for p95 latency in your workload?
