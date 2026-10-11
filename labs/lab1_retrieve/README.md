# Lab 1: Retrieve - Debug hybrid search

Follow **Workshop Studio → Lab 1** for the exact requests, the checks and each
task's **Stuck?** hints. This is the reminder beside your code.

## Task 1A: Reconnect the search that lost the Logitech

**See it fail.** Getting started saved Alex's mistyped request with
`uv run python scripts/lab_state.py start --lab 1`. Shop answers with a page of
other headphones and no error.

**Why.** Run the guide's three searches separately. Fuzzy matching finds the
Logitech on its own; do its rows ever reach `channels`? A reranker cannot
recover a product it never receives.

**Build.** In [hybrid_search.sql](hybrid_search.sql), edit only between
`LAB1_CHANNEL_START` and `LAB1_CHANNEL_END`. Add the missing `channels` branch
with the same five columns as the others: product ID, channel name `'trigram'`,
position, raw score and the contribution from
`mosaic_search.reciprocal_rank_contribution`. Saving changes nothing in Aurora
until you apply it:

```bash
uv run python scripts/apply_search_functions.py
```

**Prove it.** Repeat the identical request:

```bash
uv run python scripts/lab_terminal.py run --lab 1 --phase after
```

## Task 1B: Check the other two searches, then hand off

```bash
uv run python scripts/lab_state.py advance --lab 1
```

It replays the typo request and two controls, `G-001` (the exact ID, through
full-text search) and `G-012` (a Logitech description, through semantic
search), saves your passing evidence and prepares Lab 2.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/lab_state.py diff --lab 1` compares your marked block
with the [reference answer](solution/hybrid_search.sql) and changes nothing; it
shows the answer, so try the guide's hints first.
`uv run python scripts/lab_state.py solution --lab 1` overwrites your edit with
the answer; apply and prove it as above.

</details>
