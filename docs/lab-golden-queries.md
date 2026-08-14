# Lab golden queries

`data/evals/mosaic_labs_missions.json` is the authority for each required lab's
query, filters, target products, participant edit, broken observation, fixed
observation, and checkpoint question. This page explains how to use that
contract without creating a second copy of its values.

## Participant experiments

| Lab | Canonical query | Bad observation | Participant repair | Good observation |
|---|---|---|---|---|
| Retrieve | `G-003` / `typo-recovery` | Product 2 is absent and the trigram pool is zero | Restore the trigram CTE and candidate channel | Product 2 returns with trigram rank and contribution; hard filters still hold |
| Rank | `G-008` / `rank-with-evidence` | Product 370002 wins every arm, but collapsed contributions put 370001 at fused rank 1; reranking masks the defect | Restore `1 / (k + source_rank)` | Product 370002 is fused and final rank 1, with stable, inspectable contributions |
| Reason | `G-010` / `agentic-research` | Retrieval and evidence calls occur, but synthesis fails closed with HTTP 503 | Attach retrieved evidence IDs to product-owned synthesis state | HTTP 200, grounded comparison, and citations resolve to real evidence records |

These three are not generic example prompts. Workshop Studio runs the same
request before and after one focused change.

Five fast control queries keep the labs interactive without adding edits:

| Lab | Canonical query | Participant proves |
|---|---|---|
| Retrieve | `G-001` / `exact-identity` | FTS resolves the exact visible model name and it remains first through fusion and reranking |
| Retrieve | `G-013` / `semantic-eligibility` | A near-identical refurbished hard negative is excluded inside every arm |
| Rank | `G-007` / `compare-cheaper-alternative` | Rank movement between a mechanical keyboard and cheaper alternative is inspectable |
| Rank | `G-009` / `ranking-filter-control` | Price and headrest constraints remain deterministic gates |
| Reason | `G-020` / `evidence-grounding` | A recommendation cites resolvable evidence supporting the 12-hour claim |

The other twelve canonical queries broaden offline and release evaluation. They
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

## Verified Lab 2 movement

The release Aurora corpus establishes this deterministic top-two story:

| State | Fused rank 1 | Fused rank 2 | Final rank 1 | Final rank 2 |
|---|---:|---:|---:|---:|
| Broken RRF | 370001 | 370002 | 370002 | 370001 |
| Repaired RRF | 370002 | 370001 | 370002 | 370001 |

Product 370002 ranks first in FTS, pg_trgm, and semantic retrieval for the
explicit adjustable-lumbar query. The broken formula collapses those ordinal
differences, and the stable product-ID tie-breaker then puts 370001 first.
Cohere Rerank recovers 370002 in the final order in both states. That is the
lesson: final output alone is insufficient proof that candidate fusion is
correct.
