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

Read `k` and the candidate bounds from `db/config/retrieval.yaml`; the response's
`diagnostics.retrieval_profile` records the effective values, including
environment overrides. Keep that profile fixed during the required repair.

## Required repair: prove the arithmetic

Use the canonical `G-008` request and filters from
`data/evals/mosaic_labs_missions.json` for both states.

1. Inspect `signals` on results with different source ranks. The injected
   defect replaces each source rank with the first position, so every present
   arm contributes `1 / (k + 1)`. A candidate's broken score depends on its
   number of contributing arms, with product ID breaking equal-score ties.
2. Restore `source_rank` in `mosaic_search.reciprocal_rank_contribution` at the
   `LAB2_RRF_FORMULA` seam in `labs/lab2_rank/rrf_contribution.sql` and run
   `uv run python scripts/apply_search_functions.py`.
3. Repeat the request. Check that each contribution equals `1 / (k + rank)`
   and their sum equals `signals.rrf_score`. Compare `pre_rerank_rank`,
   `rerank_rank` and `final_rank` without treating their scores as probabilities.
4. Run `uv run python scripts/validate_lab.py --lab 2`. It checks arithmetic, repeatable fused order,
   applied reranking and provenance, then the display-specification and brand-filter controls.

The required real-catalog example also changes the visible result: the suitable Dell U2720Q is absent before repair and first after repair. It is not first in every input list. RRF admits it to the bounded rerank pool; model reranking selects it from that pool. Preserve this distinction in the guide and validators. Other worked examples retain their winner and serve as controls; see [the complete measurements](real-catalog-exercise-library.md).

## Filters

Hard eligibility rules belong in SQL and apply inside every candidate arm.
The SQL supports the filters below. Required real-catalog exercises use source-backed domain, category and brand fields; they do not invent current prices, stock or normalized attributes:

- domain/category/subcategory
- price boundaries
- availability
- compatibility
- decisive boolean/numeric attributes

A reranker scores relevance among admitted candidates. It cannot recover a
product that retrieval omitted, and it must not repair a violated hard
constraint after the fact. The controls inspect the saved candidate receipt as
well as the displayed results; a clean first page alone can hide an ineligible
candidate lower in the pool.

## No hidden ranking stage

The required path is retrievers, RRF, then bounded reranking. Availability,
price, compatibility, sponsorship, and refurbishment are deterministic SQL
eligibility predicates. Popularity or merchandising adjustments are not applied
between RRF and reranking because an invisible transformation would make the
workshop's ranking explanation false.

The final service ordering also preserves recorded exact identity and exact SKU
matches. Explain this deterministic rule when it applies; `final_rank` can
therefore differ from `rerank_rank`.

## Reranker contract

`service/retrieval.py` sends the query and each fused candidate's stored
`rerank_text` to the managed Bedrock reranker, bounded by the served retrieval
profile. `service/rerank.py` accepts indexed relevance scores and checks their
count, unique candidate indices and finite values before applying them.

The reranker does not return a per-product rationale, a requirements checklist,
or source citations. Per-arm provenance explains how a product entered fusion;
agent evidence and citation validation support claims about that product. Keep
these distinct when narrating the UI.

Retain the search event, model ID, effective profile, candidate receipt and
stage timings for comparison. `diagnostics.rerank_status` must be `applied` for
the lab proof. If required model access is unavailable, address that failure;
an unavailable fallback receipt cannot establish that reranking ran.

## Optional: standard vs weighted RRF

The default search uses equal-weight RRF. The optional Rank guide expander calls
`POST /api/retrieval/fusion-comparison` with the canonical lab request after
required completion. It does not switch `POST /api/search` to weighted fusion.

```text
Standard: score(d) = sum(1 / (k + rank_method(d)))
Weighted: score(d) = sum(weight_method / (k + rank_method(d)))
```

Only methods that returned the product contribute. Both formulas combine
positions, not raw lexical, spelling or vector scores. A channel weight changes
that channel's relative influence; `k` controls how much positions within a
channel differ. Neither produces a calibrated probability. Equal unit weights
recover standard RRF; multiplying all weights by the same positive constant
rescales totals without changing their order.

The comparison reads its `k`, candidate bounds and historical example weights
from `db/config/retrieval.yaml`. Read the returned `rrf_k` and `weights` to know
what the comparison actually used. These weights are not a tuned recommendation,
and the presence of weights in a retrieval profile does not mean ordinary search
uses them.

The service embeds the query once, uses the same query, filters and candidate
settings for both SQL calls, and checks the full candidate union and each
product's source ranks and non-fusion provenance before returning. Comparing
truncated top lists alone cannot prove identical inputs: different fused orders
can put different products above a cutoff. An input mismatch stops the comparison.

The response records both orders, source positions, fused scores, `rank_delta`
(weighted position minus standard position), and a `fusion_comparison_id`.
Negative deltas move up. `moved_count` and `orders_differ` cover the full pool.
The two order lists are truncated to the requested limit; detailed candidate
rows cover the weighted top list, with each product's position in both full orders. This path calls the embedding model and writes an
Aurora comparison record; it does not call the reranker or modify the catalog,
functions, configuration or participant repairs.

Read the result in three layers: which channel explains a move, whether that move
changes admission to the reranker, and whether judged relevance improves across
multiple queries. The comparison itself proves only the first layer. Its SQL
timings are sequential observations, not a controlled latency benchmark. Use
held-out judgments and a rule stated before measuring to justify adopting weights;
one appealing winner is insufficient.

Search results carry `canonical_group_id`, but the required search path does
not apply a diversity cap. Do not attribute a displayed order to variant
deduplication or an unimplemented merchandising stage.
