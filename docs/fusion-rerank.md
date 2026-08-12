# Fusion and reranking design

## Candidate generators

Run independent retrieval paths because each has different failure modes:

- **FTS:** exact terms, product language, models, and high-value fields
- **`pg_trgm`:** misspellings and compressed/nearby strings
- **HNSW semantic:** intent, paraphrase, use case, and benefit language

Keep source ranks and source scores. Do not throw away provenance after unioning IDs.

## Why RRF

Raw FTS rank, trigram similarity, and cosine similarity do not share a calibrated numerical scale. Reciprocal-rank fusion combines their ordinal evidence:

```text
RRF(document) = Σ 1 / (k + rank_source(document))
```

The package defaults to `k=60`, but the evaluation harness should determine whether another value works better for the query distribution.

## Filters

Hard eligibility rules belong in SQL and should be applied consistently to candidate paths where practical:

- domain/category/subcategory
- price boundaries
- availability
- compatibility
- decisive boolean/numeric attributes
- tenant or policy boundary

A reranker may reason about preferences; it should not be trusted to repair a violated hard constraint after the fact.

## No hidden ranking stage

The required path is retrievers, RRF, then bounded reranking. Availability,
price, compatibility, sponsorship, and refurbishment are deterministic SQL
eligibility predicates. Popularity or merchandising adjustments are not applied
between RRF and reranking because an invisible transformation would make the
workshop's ranking explanation false.

## Reranker contract

Input: 25–100 fused candidates with query, title, descriptions, structured attributes, and decisive constraint results.

Output per candidate:

- rerank score
- concise relevance rationale
- matched requirements
- failed/missing requirements
- optional evidence references

Persist model ID/version, latency, candidate count, and prompt/template version with every eval run.

## Diversity

Use `canonical_group_id` to prevent color/size variants of the same product from monopolizing the first page. Apply diversity after relevance and hard constraints, with a controlled maximum per canonical group.
