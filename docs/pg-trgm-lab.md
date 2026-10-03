# `pg_trgm` typo-tolerance lab

## Why it exists

Product search is unusually sensitive to misspelled brands, compressed model numbers, transposed characters, missing spaces, and category spelling errors. Semantic embeddings can sometimes mask these problems, but they should not be the only recovery mechanism for exact commercial entities.

The required example transposes `B0C2WWCFQB` to `B0C2WWFCQB` for the Logitech Zone 900 listing. The two IDs share 7 of their 15 distinct trigrams (similarity 0.467). Two other Zone 900 listings share the model name but not the listing ID, and the request must not return them. Six measured identifier cases across headphones, chairs and monitors recover the intended product after repair. A seventh already works through meaning search and is retained as a control. See [all worked examples](real-catalog-exercise-library.md).

The historical `data/evals/typo_cases.csv` targets the former synthetic catalog and is not evidence for this imported dataset.

## Indexed text

`trigram_text` holds normalized source text. The live search projection reads
the real catalog table, whose trigram index is:

```sql
CREATE INDEX real_search_trigram_idx
ON mosaic_catalog_search.product_document USING gin (trigram_text gin_trgm_ops);
```

## Required repair: reconnect a working arm

Use `G-003` from `data/evals/mosaic_labs_missions.json` with its exact filters
before and after the edit. The controlled defect is in
`mosaic_live_search.search_hybrid_rrf`: the `typo` CTE still calls the trigram
search function, but no `channels` branch reads it, and PostgreSQL never runs an
unreferenced CTE. Creating another index or lowering a threshold does not reconnect
that path.

1. Observe the successful request with the target missing. Inspect
   `diagnostics.candidate_counts.trigram_in_pool`; while broken it is zero.
2. Run `search_trigram` directly with the saved query and filters: it returns the
   target at rank 1. Then read `search_hybrid_rrf` in
   `labs/lab1_retrieve/hybrid_search.sql` to find where those rows are lost, and add the
   missing `channels` branch between the `LAB1_CHANNEL` markers.
3. Run `uv run python scripts/apply_search_functions.py`, then repeat the same request. Inspect
   the target's `signals.trigram.rank` and `rrf_contribution`. For this anchor,
   its FTS and semantic ranks remain null: the recovered product identifies
   which path changed.
4. Run `uv run python scripts/validate_lab.py --lab 1`. The exact-identity and eligibility controls must
   also pass. Finding the target alone does not establish that filters survived.

If the file is repaired but the result is unchanged, check the installed Aurora
function before altering the query. See [reset and recovery](lab-golden-queries.md#release-rule).

## How the close-spelling gates work

The served arm runs the `<%` word-similarity gate first, governed by
`pg_trgm.word_similarity_threshold`; the whole-string `%` gate, governed by
`pg_trgm.similarity_threshold`, runs only as a fallback when the first branch
returns no rows. The function's `minimum_similarity` argument is a separate
score floor on top of both gates. Read the configured values from
`db/config/retrieval.yaml` and the request's served profile. In a plan, name
the actual index node rather than inferring index use from an outer function
scan.

## Query families

Use the current worked-example library for exact transposed identifiers and each query's domain/category filters. Do not substitute an unmeasured brand typo and promise that semantic search will miss it. Correctly spelled product IDs are the required FTS control. Full model-name queries with a brand filter are the meaning/eligibility control.

## Recommended fusion behavior

- Exact brand/model/SKU hits receive lexical priority.
- Trigram is a recovery candidate source, not an automatic correction oracle.
- Preserve the original query when inspecting a run; a changed spelling is a
  different experiment, not evidence that the disconnected channel was fixed.
- Trigram rank participates in RRF; it is not naively added to cosine similarity.
- Very low-similarity candidates are excluded before reranking.
- Attribute and eligibility filters remain authoritative.

## Evaluation slices

Report metrics separately for:

- clean queries
- one-edit typos
- multi-edit typos
- brand/model typos
- category/attribute typos
- concatenated tokens

Useful metrics are recovery rate of the intended product, recall@10, MRR, false-positive rate, and added latency.
