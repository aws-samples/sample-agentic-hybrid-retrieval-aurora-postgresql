# Lab 1: Retrieve

Alex types listing ID `B07G95T3JP`, with two characters swapped, and the
intended Bose headphones are missing from the results. Full-text search and
meaning search cannot match a mistyped ID. Close spelling (`pg_trgm`) can, but
its candidates never reach fusion, and reranking can only reorder products that
retrieval returned.

## What you edit

`hybrid_search.sql`, function `mosaic_search.search_hybrid_rrf`, in two marked
blocks:

- between `LAB1_TRIGRAM_CTE_START` and `LAB1_TRIGRAM_CTE_END`: add a CTE that
  calls `mosaic_search.search_trigram` with the function's own `q`, `f`,
  `trigram_limit` and `trigram_threshold`;
- between `LAB1_TRIGRAM_CHANNEL_START` and `LAB1_TRIGRAM_CHANNEL_END`: add a
  `channels` branch with the five columns every other branch supplies: product
  ID, the channel name `'trigram'`, its rank, its raw score, and a contribution
  from `mosaic_search.reciprocal_rank_contribution`.

Change nothing else. The `fts` CTE and the `vector` branch of `channels` show
the shape to copy.

## Apply and prove

```bash
uv run python scripts/apply_search_functions.py
uv run python scripts/validate_lab.py --lab 1
```

Repeat the same request with the same filters before you validate, so the proof
reads a search that ran on your repaired SQL.

## Reference answer

[`solution/hybrid_search.sql`](solution/hybrid_search.sql). To install it,
`uv run python scripts/lab_state.py solution --lab 1` overwrites your edit.
