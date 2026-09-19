# Lab golden queries

`data/evals/mosaic_labs_missions.json` is the authority for each required lab's
query, filters, target products, participant edit, broken observation, fixed
observation, and checkpoint question. This page explains how to use that
contract without creating a second copy of its values.

## Participant experiments

| Lab | Canonical query | Bad observation | Participant repair | Good observation |
|---|---|---|---|---|
| Retrieve | `G-003` / `typo-recovery` | Neither FTS nor the semantic arm can recover product 2; the disconnected pg_trgm arm contributes nothing, so product 2 is absent from the results | Restore the trigram CTE and candidate channel | Product 2 enters through the restored trigram channel alone, reaches the first 10 results, and retains hard filters |
| Rank | `G-008` / `rank-with-evidence` | Product 370002 wins every arm; collapsed contributions give every position the same credit, so the pool below the leaders is ordered by product ID and reranking masks the defect | Restore `1 / (k + source_rank)` | Product 370002 is fused and final rank 1, with stable, inspectable contributions |
| Reason | `G-021` / `agentic-research` | Retrieval and evidence calls occur, but synthesis fails closed with HTTP 503 | Attach retrieved evidence IDs to product-owned synthesis state | HTTP 200, grounded comparison, and citations resolve to real evidence records |

These three are not generic example prompts. Workshop Studio runs the same
request before and after one focused change.

Five validator-owned controls protect the adjacent invariants without adding
participant exercises:

| Lab | Canonical query | Production validator proves |
|---|---|---|
| Retrieve | `G-001` / `exact-identity` | FTS resolves the exact visible model name and it remains first through fusion and reranking |
| Retrieve | `G-012` / `semantic-eligibility` | A near-identical refurbished hard negative is excluded inside every arm |
| Rank | `G-007` / `compare-cheaper-alternative` | Rank movement between a mechanical keyboard and cheaper alternative is inspectable |
| Rank | `G-009` / `ranking-filter-control` | Price and headrest constraints remain deterministic gates |
| Reason | `G-019` / `evidence-grounding` | A recommendation cites resolvable evidence supporting the 12-hour claim |

The other fourteen canonical queries broaden offline and release evaluation. They
are not required participant steps.

## Release rule

For each lab, capture both states from the same release Aurora cluster and
source revision:

1. `make reset-lab-N`
2. Run the request shown in Workshop Studio.
3. Save the HTTP response and relevant retrieval event.
4. `make solution-lab-N`
5. `make reset-lab-3` and `make solution-lab-3` restart the Workshop Studio
   `mosaic-api` service automatically. SQL changes are live immediately for
   Labs 1 and 2.
6. Run the identical request again.
7. Run `make validate-lab-N`.

The broken response must fail only the lesson's declared assertion. The fixed
response must satisfy every declared assertion. A screenshot is presentation
evidence, not the golden record; retain the response JSON and retrieval event.

## Lab 2 movement: what is guaranteed and what is not

Product 370002 ranks first in FTS, pg_trgm, and semantic retrieval for the
explicit adjustable-lumbar query. Under the broken `1 / (k + 1)` formula a
candidate's fused score depends only on how many arms found it, so the
guaranteed, arithmetic consequence is a collapsed pool: every candidate found
by the same number of arms shares one score, and the stable product-ID
tie-breaker orders the single-arm majority of the pool by catalog number
instead of by rank. Cohere Rerank recovers a plausible order in both states.
That is the lesson: final output alone is insufficient proof that candidate
fusion is correct.

A fused top-two swap (370001 ahead of 370002 while broken) was recorded in an
earlier measurement on the release corpus. A later hands-on run on the
current build observed 370002 first in both states, which is what the
arithmetic predicts when 370002 is found by three arms and 370001 by two:
`3 / 61` beats `2 / 61` regardless of rank. The swap therefore depends on
370001 also entering the trigram arm, which the trigram threshold decides,
and it must not be promised. The guide and the facilitator table present it
as unconfirmed; the clean-account rehearsal records which behaviour the
shipped build shows.

The repair criterion is the contribution invariant, not a mandatory rank flip.
If a differently configured run already puts 370002 first, inspect the source
ranks and contributions: `1 / (k + 1)` is still broken when distinct source ranks
receive equal credit. Restore the canonical query and filters before comparing
with the table. Reranking is required by default; an unavailable reranker fails
the request. Fused-order fallback exists only with `RERANK_REQUIRED=false`, and
its `unavailable` receipt does not pass Lab 2's reranking check.
