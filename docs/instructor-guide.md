# Instructor guide

## Pre-session checklist

- load the 500K catalog
- populate 1,024-dimensional embeddings with Cohere Embed v4 through Bedrock
- build FTS, trigram, relational, JSONB, and HNSW indexes
- run `ANALYZE`
- execute the eval harness and save a named baseline
- run the HNSW matrix on the exact Aurora configuration used in the room
- replace all sample UI performance values with measured or clearly projected data
- prewarm the most important paths, but retain one cold-cache comparison if teaching it
- verify fallback screenshots and instructor result files

## Narrative

### Opening

“Product search is where retrieval techniques stop being interchangeable. A user can misspell a model, describe a benefit instead of a feature, require a hard compatibility constraint, and still expect an explainable answer in milliseconds.”

### Lab 1 takeaway

FTS is excellent at words that exist. `pg_trgm` is excellent at recovering nearby strings. Neither understands purchase intent by itself.

### Lab 2 takeaway

Vectors understand intent, but similarity does not prove eligibility. SQL filters and decisive attributes remain authoritative.

### Lab 3 takeaway

RRF lets independently useful rankers cooperate without pretending their raw scores share a scale. Reranking operates on a bounded candidate pool and handles nuanced relevance/hard negatives.

### Lab 4 takeaway

HNSW quality is workload-specific. Measure recall against exact search, measure latency under realistic filters and concurrency, and preserve the full configuration with every result.

## Failure-safe sequence

1. SQL examples and the React application run against the balanced 5K database
   if the full catalog load is delayed.
2. Catalog and product inspection remain available when model access is
   unavailable; model-dependent retrieval must report the failure rather than
   fabricate results.
3. A saved measured benchmark result can populate the HNSW UI.
4. Scale projections are visibly labeled and never substituted for measured
   results without disclosure.

The UI does not fall back to static product JSON when the API is unavailable.
Use instructor screenshots only as presentation backup, never as workshop
retrieval evidence.

## Suggested audience questions

- Which queries are impossible to solve reliably with keyword search alone?
- Which constraints must never be left to a reranker?
- What should happen when inventory freshness conflicts across sources?
- When would a partial HNSW index or partition be justified?
- How much recall would you trade for p95 latency in your workload?
