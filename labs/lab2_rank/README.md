# Lab 2: Rank and re-rank - Tune rank fusion and reranking

Follow **Workshop Studio → Lab 2** for the exact requests, the checks and each
task's **Stuck?** hints. This is the reminder beside your code.

## Task 2A: Restore the rank contribution

**See it fail.** Lab 1's handoff saved Alex's monitor request. Semantic search
finds the ViewSonic VG2756-4K, yet it never reaches the 50 sent to reranking.

**Why.** Score a few positions with `reciprocal_rank_contribution` and compare
them with `1 / (60 + position)`. If every position earns the same contribution,
product ID decides which candidates make the cut.

**Build.** In [rrf_contribution.sql](rrf_contribution.sql), edit only the
`SELECT` between `LAB2_EDIT_START` and `LAB2_EDIT_END`, so each
source position earns `1 / (rrf_k + source_rank)`. Keep the signature, the
`double precision` result and the configured `rrf_k`. Then apply it:

```bash
uv run python scripts/apply_search_functions.py
```

**Prove it.** Repeat the identical request and grade the applied formula:

```bash
uv run python scripts/lab_terminal.py run --lab 2 --phase after
uv run python scripts/lab_exercise.py check --lab 2
```

## Task 2B: Read what reranking changed, then compare settings

In Shop, choose **Shop + search details** and compare **Before reranking (RRF)**
with **Final position**. Then judge three measured settings on labeled queries
and run the Lab 2 checks:

```bash
uv run python scripts/lab_exercise.py compare --lab 2
uv run python scripts/validate_lab.py --lab 2 --api-url http://127.0.0.1:8000
```

The comparison leaves the served settings unchanged. Decide which setting you
would ship, and why.

<details>
<summary>🔍 Optional after required completion: standard vs weighted RRF</summary>

Use the Rank guide's collapsed comparison, or read the
[implementation notes](../../docs/fusion-rerank.md#optional-standard-vs-weighted-rrf).
It compares the same candidates without changing default settings or replacing proof.

</details>

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` shows where your file differs from the
[reference answer](solution/rrf_contribution.sql), inside and outside the
markers, and changes nothing; it shows the answer, so try the guide's hints first.
`uv run python scripts/lab_state.py solution --lab 2` overwrites your edit with
the answer; apply and prove it as above.

</details>
