# Lab 1: Retrieve - Debug hybrid search

Follow **Workshop Studio → Lab 1** for the exact requests, SQL investigation,
hints and complete checks. This is the reminder beside your code.

## Broken

Start Lab 1 in the guide. Save its failed request and predict why Alex’s listing is absent.

## Diagnose

Run the guide’s three searches separately. Which finds the listing, and do its candidates reach fusion? Reranking cannot recover a candidate it never receives.

## Fix

In [hybrid_search.sql](hybrid_search.sql), edit only `LAB1_CHANNEL_START`
through `LAB1_CHANNEL_END`. Add the missing `channels` branch with five columns:
product ID, channel name, position, raw score and contribution from
`mosaic_search.reciprocal_rank_contribution`. Preserve filters and settings.

## Prove

Apply SQL, repeat the guide's identical request, then validate:

```bash
uv run python scripts/apply_search_functions.py
uv run python scripts/lab_terminal.py run --lab 1 --phase after
uv run python scripts/validate_lab.py --lab 1
```

Inspect the recovered listing's close-spelling contribution and the independent
controls. Complete the guide's source/applied-state check and your explanation.


<details>
<summary>🛠️ Recovery and reference answer</summary>

The [reference answer](solution/hybrid_search.sql) is available for full recovery.
`uv run python scripts/lab_state.py solution --lab 1` overwrites this lab's
edit. Follow the guide to apply/deploy and prove it; recovery is not completion.

</details>
