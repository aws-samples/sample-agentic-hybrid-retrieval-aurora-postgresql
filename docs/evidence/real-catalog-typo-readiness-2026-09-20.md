# Public-catalog typo story: not yet accepted

The exact user request checked was `noice cancling headfones`. The current
canonical Lab 1 spelling is `noice cancelng hedfones`; they are distinct inputs.
Neither has been accepted as the replacement-catalog lab request.

## Current generated catalog

Both requests ran through `/api/search` with the canonical Lab 1 filters,
diagnostics and reranking enabled. Product 2, Sonora WH-C720, ranked first for
both. Its only contributing retrieval arm was trigram search: FTS and semantic
ranks were null. The returned fused pool had 50 products, including one trigram
contributor and 49 semantic contributors.

| Input | Search event | Target trigram score |
|---|---|---:|
| User spelling | `1de1ff32-7153-48b5-961d-f778006ddc13` | 0.5294118 |
| Canonical spelling | `e3e71ced-ef06-46dc-9939-2a420f3ab53e` | 0.59375 |

These are repaired-path observations. This spot check did not mutate the live
Lab 1 function or repeat a broken-path run. Existing before/after evidence
applies to the canonical generated-catalog exercise, not to a public product.
Other eligible noise-canceling headphones are valid results for this category
request; their presence does not make them wrong answers.

## Preserved public product text

A read-only Aurora diagnostic examined Bose QC35 II (`B07G95TJ3P`) and
Soundcore Life Q30 (`B08VD2NX25`). This used their unchanged source titles and
embedding input text, **not a finalized production search projection**.

| Input | Bose word similarity | Soundcore word similarity | Strict FTS matches |
|---|---:|---:|---|
| User spelling | 0.4722222 | 0.4722222 | Neither |
| Canonical spelling | 0.44444445 | 0.4054054 | Neither |
| Correct spelling: noise cancelling headphones | 1.0 | 1.0 | Both |

Both misspelled inputs fall below the live word-similarity index gate, read
from Aurora as 0.5. Whole-document fallback similarity also falls below its
live 0.18 gate. These are observed settings, not new tunable declarations;
`db/config/retrieval.yaml` remains authoritative. The lower 0.20 scoring floor
does not bypass an index gate that rejects the document first.

The staged product table currently has its primary-key index only, and the
dataset reports incomplete embedding coverage. Neither sample has an embedding
loaded in Aurora staging at this check. This does not establish whether its
vector has since been generated in the local cache. A full hybrid comparison
cannot yet be claimed.

## Acceptance still required

Wire the source-faithful search projection and indexes, then run the actual
Lab 1 seam broken and repaired with the same query, filters and catalog.
Identify a source-verified suitable product absent from the broken candidate
pool and visibly recovered after restoring the close-spelling channel. Inspect
the lexical, semantic and trigram contributions separately, and include the
correctly spelled query and other natural misspellings as controls.

If semantic search already recovers a proposed target, choose a measured
example or revise the teaching claim. Do not weaken semantic retrieval, insert
the demonstration typo into product text, or force one brand above other valid
headphones to manufacture the failure. Product-type checks must also prevent
a compatible case from being treated as headphones.

Do not transfer the current in-stock and $200 claims to this historical
dataset: current availability is unknown, prices can be absent, and the Bose
sample's historical price is above that budget.

Raw local receipts are in `.local/typo-story-2026-09-20/`. No catalog rows,
retrieval settings, mission definitions or indexes changed during these checks.
