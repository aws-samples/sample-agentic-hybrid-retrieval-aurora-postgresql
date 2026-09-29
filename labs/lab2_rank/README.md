# Lab 2: Rank

Follow **Workshop Studio → Lab 2** beside this folder. In the participant
workspace, this is **02 — Rank**. The file you edit is
[rrf_contribution.sql](rrf_contribution.sql).

## Broken

Start the lab in the guide's order. The candidate lists can contain useful
products while the combined order keeps Alex's intended monitor outside the
reranking pool. Keep the failing request and your prediction in
`learning-notes.md` at the repository root.

## Diagnose

Compare products with different source positions. If every position contributes
the same amount, what decides which products reach the reranker?

The default path uses **standard, equal-weight reciprocal rank fusion**. Each
method contributes according to its product's position; a method that did not
find the product contributes nothing. Raw full-text, spelling and vector scores
are not added together. Cohere Rerank operates on the fused shortlist afterward.

`db/config/retrieval.yaml` owns `k` and the candidate bounds. It also contains
weights for a separate comparison; those channel weights are not used by the
default search. Keep the required repair's settings fixed.

## Fix

Edit only the body of `mosaic_search.reciprocal_rank_contribution`, between
`LAB2_RRF_FORMULA_START` and `LAB2_RRF_FORMULA_END`. Make it agree with the
rank-dependent contribution in your graded query. Preserve its signature,
`double precision` return type and supplied `rrf_k`.

Lab 1's hybrid search calls this function once for each method that found a
product. Follow the guide's judged-query exercise before deciding whether a
retrieval setting improves the result.

## Prove

Apply the SQL, repeat the identical request, then validate:

```bash
uv run python scripts/apply_search_functions.py
```

After repeating the request and completing the guide's graded work:

```bash
uv run python scripts/validate_lab.py --lab 2
```

Keep your own explanation and proposal decision in `learning-notes.md`.

<details>
<summary>Optional after required completion: standard vs weighted RRF</summary>

The Rank guide's **Go deeper: standard vs weighted RRF** expander compares the
same candidates with both formulas. It shows the configured channel weights,
changes in fused position and what those changes do not establish. The
[implementation notes](../../docs/fusion-rerank.md#optional-standard-vs-weighted-rrf)
explain the comparison endpoint. This exploration does not switch the default
or replace the required Lab 2 checks.

</details>

<details>
<summary>Recovery and reference answer</summary>

The [reference answer](solution/rrf_contribution.sql) is available when you want
full recovery. `uv run python scripts/lab_state.py solution --lab 2`
overwrites the exercise with that answer. Follow the guide to apply and prove it;
recovery alone is not completion.

</details>
