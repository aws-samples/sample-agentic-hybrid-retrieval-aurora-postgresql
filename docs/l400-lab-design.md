# One room, three engineering decisions

Alex already has a desk and laptop. The required labs help him find the
headphones he saved, keep a suitable monitor in reach, and evaluate the monitor
and a wheeled chair using source records. The headphone evidence check closes
the loop. No lab silently changes his needs or treats a missing specification
as a negative product feature.

## Required format

The governed workshop supplied the presentation pattern: a named scenario,
story connection, concrete objectives, architecture, bounded work, independent
proof, explanation and next step. Mosaic retains its three existing repairs.
Each guide uses the same headings:

1. Scenario and objectives, with a per-task time budget.
2. Architecture and concepts, showing deployed components and their roles.
3. Observe, diagnose, repair and prove.
4. Conclusion and takeaways.
5. Troubleshooting.
6. Next, carrying Alex's result into the following lab.

The main path asks for a hypothesis before revealing a diagnosis. No guide
prints the reference repair; Hint 4 restores it through `lab_state.py solution`
without showing it, and `validate_workshop.py` fails if a page prints it. Each lab
has one graded exercise the participant writes, checked by
`scripts/lab_exercise.py` against independently computed answers. Deeper
references and manual control requests are collapsed; required measurements are
visible. `learning-notes.md` records the
prediction, observed contradiction, decision, evidence IDs and recovery use.

## What makes the work deeper

| Lab | Customer outcome | What the participant builds | Graded against |
|---|---|---|---|
| Retrieve (explain a mechanism) | Find the saved Bose listing | The derivation of each method's behavior from `websearch_to_tsquery`, `show_trgm` and `word_similarity`; the trigram CTE and channel from a contract; a recall query for the filtered vector search | Exact neighbors the grader computes itself, with the planner's plan (btree + sort) and with HNSW forced. Measured 2026-09-22 under the headphones filter: forced HNSW returns 150 rows at recall 0.467, and the obvious `ORDER BY embedding <=> v` ground truth is itself served by HNSW |
| Rank (write an algorithm, then decide) | Recover a documented 27-inch 4K/90W monitor | RRF in SQL over the three installed search functions; the repair that makes production agree with it; one setting change with a rule stated in advance | An independent fusion at `k` = 1, 10, 30, 60 and 120 (measured: the broken run saves 2 distinct scores across 50 rows; the Dell's combined position is 7, 9, 17, 24, 24), then the proposal replayed over 141 ESCI judged queries and four reviewed chair controls. Measured: cutoff 75 admits 24 more Exact products (18 better, 0 worse) in one billed rerank unit; `k`=120 admits 5 more (p=0.125) |
| Reason (specify a contract) | Support the monitor and wheeled-chair choices; revisit the headphones | Tests for `register_evidence`, then the repair; a claims query separating cited evidence from imported reviews and source rating counts; the loop query | The reference repair (must pass) and four faulty variants (each must fail); an independent evidence count; citation mutations; the loop query's zero formula error |

Labs 1 and 2 run their investigations directly in `psql` against installed
Aurora functions and saved search tables. `scripts/lab_terminal.py` only runs
the app request and prepares IDs and parameters; it does not repair the lab.
Lab 3 runs the agent from the terminal and uses SQL to inspect its tools and
evidence, plus `scripts/investigate_lab.py` for the application citation checks. It does not modify products,
vectors or production settings. The scan experiment rolls back its local
settings. The ranking comparison rejects differing requests, filters, profiles
or catalog identities. Citation mutations exist only in memory.

## Acceptance boundaries

- Lab 1 enforces `absent_target_signals`, as well as a trigram signal. A product
  found by another method cannot substantiate an only-trigram claim.
- Lab 2's mission declares a final top-three bound. Correct arithmetic and
  recovery into the list remain essential; an exact managed-model first place
  is not required. The browser and command-line checks enforce the same bound
  and the same only-trigram condition for Lab 1.
- Monitor and chair evidence is specification-based. No imported review
  excerpts are promised for those two records. The Bose control provides the
  sampled-review comparison and is saved beside the Lab 3 completion receipt
  so participants can read its actual answer.
- A citation checker can reject specific bad inputs without proving every
  natural-language statement true. Participants still read the claim and record.
- A fresh query vector is shared across the direct-method experiment. Stored
  search events do not contain the original vector; the probe explicitly does
  not call its result a byte-identical replay.
- Returned-row count is not recall. Equal counts at two scan settings are
  legitimate; fewer eligible products than the limit is not scan starvation.
- Rank sensitivity shows the formula's behavior, not an optimal parameter.
  Single-request timings include environment and cache effects. Historical
  synthetic-catalog quality numbers are not measurements of this real catalog.

## Pacing and release

The source mission contract remains 10 minutes of introduction, 10 Retrieve,
10 Rank, 20 Reason including completion, and 10 flex. The guides redistribute
time from transcription to diagnosis and proof. A timed participant run is
still required to confirm that the experience fits the budget; edited time
tables are not a rehearsal result.

Source checks, locally edited Workshop Studio pages, deployed EC2 proof and
publication are separate states. The fresh-account rehearsal remains excluded
from this work. The known catalog accessory-classification finding must be
resolved and the affected example receipts remeasured before claiming final
session readiness.

## Verification

The [September 22 investigation report](evidence/l400-investigation-2026-09-22.json)
records the Aurora method counts, eligible population, actual plan nodes, paired
search IDs, ranking arithmetic and citation challenges. All 44 live checks across
the three lab validators passed. The report identifies the code measured and
separates current probes from reused before/after records. This is technical
validation, not a timed participant run or a publication approval.
