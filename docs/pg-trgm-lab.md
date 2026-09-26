# `pg_trgm` typo-tolerance lab

## Why it exists

Product search is unusually sensitive to misspelled brands, compressed model numbers, transposed characters, missing spaces, and category spelling errors. Semantic embeddings can sometimes mask these problems, but they should not be the only recovery mechanism for exact commercial entities.

The required example transposes `B07G95TJ3P` to `B07G95T3JP` for the Bose QuietComfort 35 II listing. Six measured identifier cases across headphones, chairs and monitors recover the intended product after repair. A seventh already works through meaning search and is retained as a control. See [all worked examples](real-catalog-exercise-library.md).

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
`mosaic_live_search.search_hybrid_rrf`: the trigram search function exists, but its
CTE and candidate-channel union are disconnected. Creating another index or
lowering a threshold does not reconnect that path.

1. Observe the successful request with the target missing. Inspect
   `diagnostics.candidate_counts.trigram_in_pool`; while broken it is zero.
2. Locate `LAB1_TRIGRAM_CTE` and `LAB1_TRIGRAM_CHANNEL` in
   `db/sql/09_search_functions.sql`. Follow the arm's product ID, rank and score
   into fusion, and restore both seams.
3. Run `make db-apply-search-functions`, then repeat the same request. Inspect
   the target's `signals.trigram.rank` and `rrf_contribution`. For this anchor,
   its FTS and semantic ranks remain null: the recovered product identifies
   which path changed.
4. Run `make validate-lab-1`. The exact-identity and eligibility controls must
   also pass. Finding the target alone does not establish that filters survived.

If the file is repaired but the result is unchanged, check the installed Aurora
function before altering the query. See [reset and recovery](lab-golden-queries.md#release-rule).

## Optional SQL inspection

The historical `make lab-01` probe describes the former catalog. It is not a current acceptance test. Inspect the live schema with the guide’s direct query instead. Its original operator demonstration compares:

1. the strict `websearch_to_tsquery` match count for the misspelled query;
2. `mosaic_search.search_fts`, including its conjunctive backoff;
3. `mosaic_search.search_trigram` on that query;
4. the execution plan for the `<%` word-similarity gate;
5. the script's score-floor sweep.

This is the read-only inspection script `db/sql/lab_01_typo_tolerance.sql`,
not the required repair or its acceptance gate. Its arm calls use empty
filters, and its plan and sweep use a single misspelled token. Those observations
explain the operators but do not prove the filtered mission request. In the
plan, name the actual index node rather than inferring index use from an outer
function scan.

The served arm runs the `<%` word-similarity gate first, governed by
`pg_trgm.word_similarity_threshold`; the whole-string `%` gate, governed by
`pg_trgm.similarity_threshold`, runs only as a fallback when the first branch
returns no rows. The function's `minimum_similarity` argument is a separate
score floor on top of both gates. Read the configured values from
`db/config/retrieval.yaml` and the request's served profile. The optional SQL
sweep changes a score predicate; it does not change either index gate.

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
