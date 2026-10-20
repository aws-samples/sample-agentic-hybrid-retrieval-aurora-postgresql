# Lab 2: Rank and re-rank - Tune rank fusion and reranking

Follow **Workshop Studio → Lab 2** for the exact requests, the checks and each
section's **Stuck?** hints. This is the reminder beside your code.

Alex has found his headphones. Now he needs a monitor with USB-C charging.
Keep your retrieval repair and inspect the monitor request that Lab 1's
handoff saved: does the intended listing survive ranking?

## Send Alex's monitor request

In `psql`, load `.local/lab-2/context.psql` with `\i` in its own paste. Follow
the guide's query to compare the ViewSonic VG2756-4K's semantic position with
its membership in the fused shortlist. Then score a few positions with
`reciprocal_rank_contribution` and compare them with `1 / (60 + position)`. If
every position earns the same contribution, product ID decides which
candidates make the cut.

## Give each position its own score

In [rrf_contribution.sql](rrf_contribution.sql), edit only the
`SELECT` between `LAB2_EDIT_START` and `LAB2_EDIT_END`, so each
source position earns `1 / (rrf_k + source_rank)`. Keep the signature, the
`double precision` result and the configured `rrf_k`. Then apply it:

```bash
uv run python scripts/apply_search_functions.py
```

Repeat the identical request and grade the applied formula:

```bash
uv run python scripts/lab_terminal.py run --lab 2 --phase after
uv run python scripts/lab_exercise.py check --lab 2
```

## See what reranking changes

Run Alex's request with reranking off, then on, and compare the two pages of
12; [rerank_off_on.py](rerank_off_on.py) shows that the calls differ only in
`rerank`. Shop is an optional view of this evidence.

```bash
uv run python labs/lab2_rank/rerank_off_on.py
```

## Compare settings, then hand off

Compare candidate admission under three settings on judged queries:

```bash
uv run python scripts/lab_exercise.py compare --lab 2
```

The comparison leaves served settings unchanged and calls no reranker.
Nominate a setting to test next; final relevance, latency and actual cost need
separate measurement before shipping.

The handoff repeats Alex's request and two Dell
requests that must still work, saves the passing evidence, then installs the
Retrieval agent starter for Lab 3. If it is interrupted, run it again:

```bash
uv run python scripts/lab_state.py advance --lab 2
```

<details>
<summary>🔍 Optional after required completion: standard vs weighted RRF</summary>

Use the Rank guide's collapsed comparison, or read the
[implementation notes](../../docs/fusion-rerank.md#optional-standard-vs-weighted-rrf).
It compares the same candidates without changing default settings or replacing proof.

</details>

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` names the lines of your file that differ from the
[reference answer](solution/rrf_contribution.sql), inside and outside the markers, without
printing it, and changes nothing. Add `--answer` to see the answer's lines;
try the guide's hints first.
`uv run python scripts/lab_state.py solution --lab 2` overwrites your edit with
the answer; apply and prove it as above.
`uv run python scripts/lab_state.py finish --lab 2` does all of it in one
command, with the hand-off.

</details>
