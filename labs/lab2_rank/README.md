# Lab 2: Rank and rerank - Tune rank fusion and reranking

Follow **Workshop Studio → Lab 2** for the exact requests, the checks and each
section's **Stuck?** hints. This is the reminder beside your code.

Alex has found his headphones. Now he needs a monitor with USB-C charging.
Keep your retrieval repair and inspect the monitor request that Lab 1's
handoff saved: does the intended listing survive ranking?

## Trace Alex's monitor request

At the shell prompt, open `psql` with the request loaded,
`PSQLRC=.local/lab-2/context.psql psql`. Follow
the guide's query to compare the ViewSonic and the BenQ. Did a higher semantic
position earn more points? Enter `\q` to return to the shell.

## Give each position its own score

In [rrf_contribution.sql](rrf_contribution.sql), replace the `1.0` after the plus
sign with the product's position. Save the file and apply it at the shell prompt:

```bash
uv run python scripts/apply_search_functions.py
```

At the shell prompt ending in `$`, repeat the identical request and grade the applied
formula:

```bash
uv run python scripts/lab_request.py send --lab 2 --phase after
uv run python scripts/lab_exercise.py grade --lab 2
```

## See what reranking changes

Run Alex's request with reranking off, then on, and compare the two pages of
12; [rerank_off_on.py](rerank_off_on.py) shows that the calls differ only in
`rerank`.

```bash
uv run python labs/lab2_rank/rerank_off_on.py
```

In **Shop**, select **Lab 2: Alex’s monitor request**. Open **Why this match** on
the ViewSonic to see how its position changed. Then choose **Compare positions**
above the results and check the Acer's resolution.

## Test whether changing k helps, then hand off to Lab 3

Test whether changing `k` lets more judged right answers reach reranking:

```bash
uv run python scripts/lab_exercise.py compare --lab 2
```

The comparison leaves served settings unchanged and calls no reranker. The
`k = 120` and `k = 30` rows keep the same search lists and shortlist of 50; decide
whether they justify changing `k = 60`, and keeping it is a valid choice. The
shortlist of 75 is optional reading: final relevance, latency and actual cost need
separate measurement before shipping a longer shortlist.

The handoff repeats Alex's request and two Dell
requests that must still work, saves the passing evidence, then installs the
Retrieval agent's starting code for Lab 3. If it is interrupted, run it again:

```bash
uv run python scripts/lab_state.py advance --lab 2
```

<details>
<summary>🔍 Optional after required completion: standard vs weighted RRF</summary>

Use **Weighted against standard fusion** on the guide's **Lab 2 in depth** page, or read the
[implementation notes](../../docs/fusion-rerank.md#optional-standard-vs-weighted-rrf).
It compares the same candidates without changing default settings or replacing proof.

</details>

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` names the lines of your file that differ from the
[reference answer](solution/rrf_contribution.sql), inside and outside the markers, without
printing it, and changes nothing. Add `--answer` to see the answer's lines;
try the guide's hints first.
`uv run python scripts/lab_state.py apply-solution --lab 2` overwrites your edit with
the answer; apply and prove it as above.
`uv run python scripts/lab_state.py finish --lab 2` does all of it in one
command, with the handoff. If Lab 1 is not complete (it never handed off, or you
restarted or changed it after its handoff), this finishes Lab 1 with the reference
answer first.

</details>
