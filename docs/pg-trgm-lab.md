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

`trigram_text` combines normalized title, brand, model, subcategory, and aliases. The index is:

```sql
CREATE INDEX product_trigram_gin_idx
ON catalog.product USING gin (trigram_text gin_trgm_ops);
```

## Core exercise

Run `sql/05_typo_tolerance_lab.sql` and compare:

1. FTS results for the misspelled query
2. whole-identity `%` candidates for models and SKUs
3. token-level `<%` word-similarity candidates for prose
4. score thresholds from 0.60 through 1.00
5. the indexed execution plan

## Query families

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
