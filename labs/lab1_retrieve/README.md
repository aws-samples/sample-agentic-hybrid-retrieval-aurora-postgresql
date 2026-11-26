# Lab 1: Retrieve - Debug hybrid search

Follow **Workshop Studio → Lab 1** for the exact requests, the checks and each
section's **Stuck?** hints. This is the reminder beside your code.

Alex starts his home office with the Logitech Zone 900 headphones. His
mistyped listing ID returned other headphones; find where the intended one
disappears.

## Trace Alex's mistyped ID

Getting started saved Alex's mistyped request with
`uv run python scripts/lab_state.py start --lab 1`. First read which searches `channels`
reads in `hybrid_search.sql`. A reranker can only reorder products that reach the
shortlist. The guide’s **Lab 1 in depth** page has the SQL for checking each search separately.

## Connect fuzzy matching

In [hybrid_search.sql](hybrid_search.sql), edit only between
`LAB1_EDIT_START` and `LAB1_EDIT_END`. Add the missing `channels` branch
with the same five columns as the others: product ID, search name `'fuzzy'`,
position, raw score and the contribution from
`mosaic_search.reciprocal_rank_contribution`. Saving changes nothing in Aurora
until you apply it. At the shell prompt ending in `$`, run:

```bash
uv run python scripts/apply_search_functions.py
```

## Prove fuzzy matching puts the Logitech back on the shortlist

At the shell prompt ending in `$`, repeat the identical request:

```bash
uv run python scripts/lab_request.py send --lab 1 --phase after
```

In **Shop**, select **Lab 1: a mistyped listing ID**. Open **Why this match** on
the Logitech to see how it reached the shortlist.

## Hand off to Lab 2

```bash
uv run python scripts/lab_state.py advance --lab 1
```

It replays the mistyped-ID request and two of Mosaic's fixed test requests, `G-001`
(the exact ID, through full-text search) and `G-012` (a Logitech description,
through semantic search), saves your passing evidence and prepares Lab 2.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` names the lines of your file that differ from the
[reference answer](solution/hybrid_search.sql), inside and outside the markers, without
printing it, and changes nothing. Add `--answer` to see the answer's lines;
try the guide's hints first.
`uv run python scripts/lab_state.py apply-solution --lab 1` overwrites your edit with
the answer; apply and prove it as above.
`uv run python scripts/lab_state.py finish --lab 1` does all of it in one
command, with the handoff. If Lab 2 has started and is not repaired yet, it stops
before the handoff; run `uv run python scripts/lab_state.py finish --lab 2`
instead, which finishes both labs and replaces your Lab 2 edits.

</details>
