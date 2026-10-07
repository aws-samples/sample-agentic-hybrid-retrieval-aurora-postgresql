# Lab 2: Rank and re-rank - Tune rank fusion and reranking

Follow **Workshop Studio → Lab 2** for the exact requests, SQL investigation,
hints and complete checks. This is the reminder beside your code.

## Broken

Start Lab 2 after Lab 1 passes. Save the failure: a suitable monitor misses the reranking pool. Predict the cause.

## Diagnose

Compare saved source positions and contributions. If different positions earn the same contribution, what chooses the cutoff? Standard, equal-weight RRF uses positions, not raw search scores.

## Fix

In [rrf_contribution.sql](rrf_contribution.sql), edit only
`LAB2_RRF_FORMULA_START` through `LAB2_RRF_FORMULA_END`. Make each source
position earn its own contribution. Preserve the signature, `double precision`
result and configured `rrf_k`. This is **2a — Rank**.

## Prove

For **2b — Re-rank**, apply SQL, repeat the identical request and grade:

```bash
uv run python scripts/apply_search_functions.py
uv run python scripts/lab_terminal.py run --lab 2 --phase after
uv run python scripts/lab_exercise.py check --lab 2
uv run python scripts/lab_exercise.py compare --lab 2
uv run python scripts/validate_lab.py --lab 2
```

Inspect combined and final positions. Complete the guide's source/applied-state
check and controls. Decide which setting you would ship, and why.
The comparison leaves served settings unchanged; use its judged results.

<details>
<summary>🔍 Optional after required completion: standard vs weighted RRF</summary>

Use the Rank guide's collapsed comparison, or read the
[implementation notes](../../docs/fusion-rerank.md#optional-standard-vs-weighted-rrf).
It compares the same candidates without changing default settings or replacing proof.

</details>


<details>
<summary>🛠️ Recovery and reference answer</summary>

The [reference answer](solution/rrf_contribution.sql) is available for full recovery.
`uv run python scripts/lab_state.py solution --lab 2` overwrites this lab's
edit. Follow the guide to apply/deploy and prove it; recovery is not completion.

</details>
