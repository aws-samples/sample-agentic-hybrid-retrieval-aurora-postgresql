# Lab 1: Retrieve

Follow **Workshop Studio → Lab 1** beside this folder. In the participant
workspace, this is **01 — Retrieve**. The file you edit is
[hybrid_search.sql](hybrid_search.sql).

## Broken

Run the guide's start command and repeat its exact request and filters. Keep the
saved result: a plausible headphone can appear while Alex's intended listing
is missing. Record your prediction in `learning-notes.md` at the repository root.

## Diagnose

Follow the candidate path in the saved search. Run each of the three searches on
its own: which one finds the intended listing, and do its candidates reach fusion?
Reranking can only reorder products retrieval returned. The guide supplies the
request, checkpoints and hints; keep those beside the code.

## Fix

Edit only `mosaic_search.search_hybrid_rrf`, between `LAB1_CHANNEL_START` and
`LAB1_CHANNEL_END`. Add the `channels` branch for the search whose candidates never
reach fusion, with the five columns every other branch supplies: product ID, the
channel name the receipt uses, its position, its raw score and its contribution
from `mosaic_search.reciprocal_rank_contribution`. The full-text and vector
branches show the shape.

## Prove

Apply the SQL, repeat the identical request, then validate:

```bash
uv run python scripts/apply_search_functions.py
```

After repeating the request with the same filters:

```bash
uv run python scripts/validate_lab.py --lab 1
```

Finish the guide's checks and write your own explanation in `learning-notes.md`.
Editing the file alone does not change Aurora.

<details>
<summary>Recovery and reference answer</summary>

The [reference answer](solution/hybrid_search.sql) is available when you want
full recovery. `uv run python scripts/lab_state.py solution --lab 1`
overwrites the exercise with that answer. Follow the guide to apply and prove it;
recovery alone is not completion.

</details>
