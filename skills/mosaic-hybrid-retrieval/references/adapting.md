# Adapting the skill

Use this package as an architectural contract, not as a promise that Mosaic's
catalog schema or measured tuning fits another workload.

## Keep these invariants

- Apply hard eligibility in every retrieval arm before its candidate limit.
- Bound each arm and the fused pool explicitly.
- Fuse independent ranked lists before model reranking.
- Let reranking reorder only the bounded pool; it must not introduce candidates.
- Preserve exact identifier matches when a domain has authoritative identifiers.
- Persist the query, applied filters, configuration, candidates, and rank signals
  needed to replay what happened.
- Separate the served result window from the downstream evidence grant.
- Require evidence and comparison calls to stay inside that grant.
- Keep source attribution attached to the returned evidence.
- Keep transport adapters thin. They map arguments and envelopes but do not
  reimplement retrieval or scope policy.

## Replace these Mosaic choices

| Area | Mosaic choice | What an adopter must decide |
|---|---|---|
| Retrieval projection | `mosaic_search.product_document` over commerce products | The entity, stable identifier, searchable text, hard-filter columns, and refresh process for the target domain |
| Taxonomy and filters | Three product domains, category, brand, stock, price, rating, and attributes | The domain vocabulary and which constraints are hard eligibility rather than ranking preferences |
| Full-text search | PostgreSQL `english` text search configuration and product-field weights | Language configuration, dictionaries, tokenization, field weights, and multilingual strategy |
| Fuzzy matching | `pg_trgm` over Mosaic identity text | Which fields tolerate spelling variation and the measured similarity threshold |
| Embeddings | Cohere Embed v4, 1,024 dimensions, cosine HNSW | Embedding model, dimensions, distance operator, document construction, migration plan, and index parameters |
| Fusion and reranking | Unweighted RRF plus managed reranking | Candidate depths, fusion constant, rerank model, exact-match policy, latency budget, and fallback behavior |
| Evidence | Product specifications and reviews | Evidence units, source URI/revision contract, freshness, ranking query, and citation resolver |
| Response schema | Product summaries and commerce rank signals | The smallest stable entity and provenance shape callers actually need |
| Identity | Single-attendee UUID handles | Principal and tenant binding for retrieval events, evidence, comparison, and replay |
| Receipt storage | Append-only search and result events | Retention, redaction, encryption, write capacity, deletion, and audit requirements |
| Evaluations | Mosaic missions, target products, and scorecard | Representative queries, judgments, failure cohorts, budgets, and release thresholds for the new domain |

## Adapt in this order

1. Define the target entity, authoritative identifier, evidence unit, and hard
   eligibility rules.
2. Build one denormalized Aurora retrieval projection that exposes those filters
   beside the searchable text and vector.
3. Replace text construction, language configuration, embedding model, vector
   dimensions, and index operator as one versioned migration.
4. Port the lexical, fuzzy, and semantic arms while preserving pre-limit
   eligibility.
5. Measure candidate depths, fusion, reranking, and HNSW settings on the new
   corpus. Do not copy Mosaic's numbers as production defaults.
6. Replace the logical skill schemas and update the HTTP or MCP adapter mapping.
7. Bind retrieval scopes and replay to the deployment's real principal and
   tenant model.
8. Create domain evaluations with explicit falsifiers, then run them through
   the same production retrieval path the application serves.

## Definition of done

- A logical skill request maps unambiguously to the deployed transport.
- A hard filter cannot admit an ineligible candidate through any arm.
- Reranking cannot add a candidate or displace an authoritative exact match.
- Evidence and comparison refuse products outside the declared grant.
- A persisted receipt explains the exact served order without recomputation.
- A shared deployment cannot replay another principal's query or receipts.
- The evaluation set proves both target success and known failure directions on
  the adapted corpus.

For Mosaic's checked HTTP mapping, see
[`http-api.md`](http-api.md). For parent-agent and hosting boundaries, see
[`composition.md`](composition.md).
