# Lab 2: Rank

Alex asks for a monitor for coding, with a 4K screen and USB-C charging.
Reciprocal rank fusion combines each channel's ranks into one order before
reranking. When the contribution is the same at every rank, the products found
by a single channel all tie, the 50-product cutoff is decided by product ID, and
the monitor Alex needs never reaches reranking.

## What you edit

`rrf_contribution.sql`, the body of `mosaic_search.reciprocal_rank_contribution`
between `LAB2_RRF_FORMULA_START` and `LAB2_RRF_FORMULA_END`. Return the
per-method contribution your graded query uses. Keep the signature, the
`double precision` result and the configured `rrf_k`.

Lab 1's `search_hybrid_rrf` calls this function once for each channel that found
a product, so this one formula decides how the channel ranks combine.

## Apply and prove

```bash
uv run python scripts/apply_search_functions.py
uv run python scripts/validate_lab.py --lab 2
```

## Reference answer

[`solution/rrf_contribution.sql`](solution/rrf_contribution.sql). To install it,
`uv run python scripts/lab_state.py solution --lab 2` overwrites your edit.
