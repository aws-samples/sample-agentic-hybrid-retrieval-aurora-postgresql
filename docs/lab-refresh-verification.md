# Real-catalog lab verification

Local verification on 2026-09-21. The three exercises work against the prepared
Aurora catalog. This is not a Workshop Studio publication or a fresh-environment
rehearsal.

## What participants build

| Lab | Before repair | After repair | Budget |
|---|---|---|---|
| Retrieve | A mistyped Bose listing ID misses the requested product. Related headphones are not the requested listing. | The spelling search recovers Bose QuietComfort 35 II at position 1. | 10 minutes |
| Rank | Collapsing every reciprocal-rank contribution to rank 1 drops Dell U2720Q from the combined pool. A visible HP Z27n result explicitly says 1440p despite the 4K request. | Dell enters the combined list at position 24 and reaches position 1 after reranking. | 10 minutes |
| Reason | Disconnected evidence registration makes the monitor-and-chair request fail with HTTP 503. | Separate searches, product comparison and source checks support an answer covering both products. | 20 minutes, including completion |

The introduction takes 10 minutes. Required work ends at minute 50, leaving
10 minutes for recovery, questions or one optional exercise. These are teaching
budgets, not measured participant completion times.

Each guide follows Observe → Diagnose → Repair → Prove. The visible path gives
the action, the result to inspect and the next step. Mechanism explanations,
manual control requests, saved-response fields, troubleshooting and advanced
work are expandable. Four progressive hints end with the complete repair.
Pace markers start proof by minute 7 in Labs 1 and 2 and minute 13 in Lab 3.
The required controls still run in the production validator; participants do
not need to repeat them manually. Completion regrades the saved Lab 3 runs
against current code and records without two additional model calls.

## Breadth and limits of the examples

[The example library](real-catalog-exercise-library.md) retains 14 paired query
variants, or 28 HTTP searches. Six listing-ID spelling cases recover a missing
target across headphones, monitors and chairs. The library also preserves an
unchanged identity control, unchanged feature-query winners and one monitor
wording variant that still misses its target. It is a teaching sample, not a
representative benchmark of 500,000 products.

No product descriptions, images, reviews or embeddings were altered to create
these outcomes. The faults are in the code participants repair. Both SQL
experiments restored the original live functions byte-for-byte. The Lab 3
source seam was also restored after observing its failure.

## Verification results

| Check | Result | Scope |
|---|---|---|
| Live catalog identity | PASS | `reviews-2023-500k-v1`, 500,000 products and embeddings; Cohere Embed v4, 1024 dimensions |
| Live mission validation | PASS | 110 checks against current catalog targets |
| Production Lab 1 validator | PASS | 10 checks; automated run took 32.2 seconds |
| Production Lab 2 validator | PASS | 15 checks; automated run took 39.4 seconds |
| Production Lab 3 validator | PASS | 19 checks; automated run took 134.1 seconds |
| Lab 3 saved-run regrading | PASS | Completion path revalidated both runs without generating new answers |
| Optional builder tool | PASS | Separate Bose and Sony requests retained their brand and category filters and matched saved search events |
| Workshop guide suite | PASS | 131 tests, plus participant-query, page structure, repair, link/citation, shell-fence, completion and session-contract checks |
| UI suite | PASS | 694 tests; 62 affected retrieval tests and 17 Discover/walkthrough tests rerun after final edits |
| Production UI build | PASS | Existing large-chunk warning remains |
| Offline Python suite | PARTIAL | 1,423 passed, 15 skipped, 44 deselected; two scorecard attribution tests fail because the historical baseline does not describe this catalog/code |
| Configuration gates | PASS | Retrieval settings profile and configuration tripwire |
| Bootstrap delivery-copy parity | PASS | Local source and Workshop Studio bootstrap files are byte-identical; no publication claim |

Browser inspection confirmed the Bose recovery in Shop and Playground and
Dell's combined position 24 → final position 1. Playground now requests the
mission's 10 results. Its before/after table explicitly describes positions
among displayed products rather than implying it ran a separate search with
reranking disabled.

Discover's profile and walkthrough panels share their top and bottom edges;
the visible progress bars also end exactly at the grey profile's bottom edge.
The room retains its native aspect ratio, and the chair highlight includes the
headrest, arms, base and wheels. Laptop and narrow-screen checks found no
horizontal overflow or clipped highlight. The introduction advances every four
seconds while visible, plays once and stops at the vision. Next and Pause remain
available, progress marks are non-clickable, and a resting mouse no longer
pauses the introduction. Replay starts another pass; reduced-motion viewers
retain manual control. The 17 Discover/walkthrough tests and build passed after
these changes.

## Proof files

- `data/evals/real_catalog_exercise_verification.json`: all 14 paired cases,
  including controls and unsuccessful wording.
- `data/evals/real_catalog_lab_products.json`: product text and source/embedding
  hashes for the selected examples.
- `.local/real-products/sql-lab-before-after.json`: broken, repaired and repeated
  SQL lab searches, plus byte-identical restoration confirmation.
- `.local/real-products/lab3-broken-proof.json`: observed broken evidence path.
- `.local/real-products/lab-3-final-validation.json`: saved repaired runs
  `353c07ff-cd58-45bb-892f-57a472386578` and
  `ee43cf3b-ca97-43ea-a283-56f4b57ece70`.
- `.local/real-products/final-live-lab-validation.log`: the 44 live checks.
- `.local/real-products/real-catalog-builder-proof.json`: optional tool checks.
- `.local/real-products/lab-refresh-final-python-recheck.log`: complete offline
  Python results, including both remaining failures.

These results use an uncommitted worktree based on
`c6300668ab27b4abb956d64cf2d58f6f84c14654`, not a published release SHA. Local
agent validation used `global.anthropic.claude-sonnet-5`; the application delivery
configuration has a separate Sonnet 4.6 pin. Local proof does not establish
identical behavior under the participant delivery model or IAM role.

## Before publication

1. Package and validate the real-catalog bootstrap assets and load path. The
   current bootstrap still uses the historical cache route; its new dataset
   identity check prevents a stale 500,000-row catalog from passing these labs.
2. Separate current-catalog evaluation cases from historical synthetic cases,
   review relevance judgments and measure a new scorecard. Keep the two
   attribution failures visible until the new measurements are valid.
3. Prepare current exact-neighbor ground truth before treating the optional
   HNSW comparison as a measured exercise.
4. Verify the delivery model, immutable source pin and published asset hashes
   after source release. Workshop Studio publication remains user-owned.
5. Complete the fresh-environment rehearsal, excluded from this pass.

No source commit, push, Studio re-pin, asset upload or publication was performed
as part of this lab-refresh verification.
