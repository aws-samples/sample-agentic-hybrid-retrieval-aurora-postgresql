# Lab 1: Retrieve - Debug hybrid search

Follow **Workshop Studio → Lab 1** for the exact requests, the checks and each
section's **Stuck?** hints. This is the reminder beside your code.

Alex starts his home office with the Logitech Zone 900 headphones. His
mistyped listing ID returned other headphones; find where the intended one
disappears.

## Send Alex's mistyped ID

Getting started saved Alex's mistyped request with
`uv run python scripts/lab_state.py start --lab 1`. In `psql`, load it with
`\i .local/lab-1/context.psql` in its own paste, then count what each search contributed to
`search_hybrid_rrf`: all 50 candidates come from semantic search, no Logitech,
no error. Then run the three searches separately. Fuzzy matching finds the
Logitech on its own; do its rows ever reach `channels`? A reranker cannot
recover a product it never receives.

## Connect fuzzy matching

In [hybrid_search.sql](hybrid_search.sql), edit only between
`LAB1_EDIT_START` and `LAB1_EDIT_END`. Add the missing `channels` branch
with the same five columns as the others: product ID, channel name `'trigram'`,
position, raw score and the contribution from
`mosaic_search.reciprocal_rank_contribution`. Saving changes nothing in Aurora
until you apply it:

```bash
uv run python scripts/apply_search_functions.py
```

## Prove the Logitech is first again

Repeat the identical request:

```bash
uv run python scripts/lab_terminal.py run --lab 1 --phase after
```

## Check the exact ID and his description, then hand off

```bash
uv run python scripts/lab_state.py advance --lab 1
```

It replays the typo request and two of Mosaic's fixed test requests, `G-001`
(the exact ID, through full-text search) and `G-012` (a Logitech description,
through semantic search), saves your passing evidence and prepares Lab 2.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` names the lines of your file that differ from the
[reference answer](solution/hybrid_search.sql), inside and outside the markers, without
printing it, and changes nothing. Add `--answer` to see the answer's lines;
try the guide's hints first.
`uv run python scripts/lab_state.py solution --lab 1` overwrites your edit with
the answer; apply and prove it as above.
`uv run python scripts/lab_state.py catch-up --lab 1` does all of it in one
command, with the hand-off.

</details>
