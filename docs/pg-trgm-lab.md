# `pg_trgm` typo-tolerance lab

## Why it exists

Product search is unusually sensitive to misspelled brands, compressed model numbers, transposed characters, missing spaces, and category spelling errors. Semantic embeddings can sometimes mask these problems, but they should not be the only recovery mechanism for exact commercial entities.

The package ships **5,000 deterministic typo cases** in `data/evals/typo_cases.csv`, covering:

- adjacent-character transposition
- missing characters
- substitutions
- duplicated characters
- removed spaces
- light phonetic substitutions

## Indexed text

`trigram_text` combines normalized title, brand, model, SKU, category path, aliases, and tags. The index the API's arm actually uses is:

```sql
CREATE INDEX product_document_trigram_gin_idx
ON mosaic_search.product_document USING gin (trigram_text gin_trgm_ops);
```

## Core exercise

Run `db/sql/lab_01_typo_tolerance.sql` and compare:

1. the strict `websearch_to_tsquery` match count for the misspelled query
2. `mosaic_search.search_fts` for the same query, including its conjunctive
   backoff
3. `mosaic_search.search_trigram` for the same query and filters
4. the indexed execution plan for the `<%` word-similarity gate
5. score thresholds from 0.60 through 1.00

The served arm runs the `<%` word-similarity gate first, governed by
`pg_trgm.word_similarity_threshold`; the whole-string `%` gate, governed by
`pg_trgm.similarity_threshold`, runs only as a fallback when the first branch
returns no rows. The function's `minimum_similarity` argument is a separate
score floor on top of both gates.

## Query families

The all-miss anchor, where every token defeats the stemmer and only the
trigram arm recovers the target:

```text
noice cancelng hedfones
```

Partial-miss queries, where at least one token is spelled correctly (or stems
correctly: `canceling` and `cancelling` both stem to `cancel`) so FTS still
contributes and the trigram arm is one signal among several. Contrast these
with the anchor rather than treating them as equivalent:

```text
noice canceling hedphones
quiet mechancial keybaord
ergonmic ofice chair
carbon plated marthon shoe
gps runing wacth
standingdesk converter
```

## Recommended fusion behavior

- Exact brand/model/SKU hits receive lexical priority.
- Trigram is a recovery candidate source, not an automatic correction oracle.
- The original query and corrected/normalized form are both logged.
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
