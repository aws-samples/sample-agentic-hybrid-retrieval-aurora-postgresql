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
   `LAB2_RRF_FORMULA` seam in `db/sql/09_search_functions.sql` and run
   `make db-apply-search-functions`.
3. Repeat the request. Check that each contribution equals `1 / (k + rank)`
   and their sum equals `signals.rrf_score`. Compare `pre_rerank_rank`,
   `rerank_rank` and `final_rank` without treating their scores as probabilities.
4. Run `make validate-lab-2`. It checks arithmetic, repeatable fused order,
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

## Optional comparisons

Historical weighted fusion is a separate experiment. Before comparing its
ordering with unweighted RRF, compare the full candidate unions: truncated
served windows can contain different IDs solely because their ordering differs.

Search results carry `canonical_group_id`, but the required search path does
not apply a diversity cap. Do not attribute a displayed order to variant
deduplication or an unimplemented merchandising stage.
