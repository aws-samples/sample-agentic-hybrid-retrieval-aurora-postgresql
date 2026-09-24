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
has graded work the participant writes, checked by `scripts/lab_exercise.py`
against independently computed answers. Required measurements are visible;
deeper explanation and reference payloads sit in expanders labeled **Go deeper**,
**Reference** or **Answer**. `learning-notes.md` holds one written prediction and
one two-sentence explanation per lab, plus Alex's brief in the Conclusion; other
questions are for discussion.

## What makes the work deeper

| Lab | Customer outcome | What the participant builds | Graded against |
|---|---|---|---|
| Retrieve (explain a mechanism) | Find the saved Bose listing | An account, from one query over the installed search functions, the listing's lexemes and `word_similarity`, of why only close spelling can match (`show_trgm`, `\sf` and the raw plans are optional); the trigram CTE and channel from a contract; a recall query for the filtered vector search | Exact neighbors the grader computes itself, with the planner's plan (btree + sort, about 286 ms) and with HNSW forced (39–47 ms). Forced recall measured 0.287 (2026-09-23), 0.440 and 0.467 (2026-09-24) at a full 150 rows; the obvious `ORDER BY embedding <=> v` ground truth is itself served by HNSW |
| Rank (write an algorithm, then decide) | Recover a documented 27-inch 4K/90W monitor | RRF in SQL over the three installed search functions (the searches and their union are given; the fusion and tie-break are the participant's); the repair that makes production agree with it; one setting change with a rule stated in advance | An independent fusion at `k` = 1, 10, 30, 60 and 120 (measured: the broken run saves 2 distinct scores across 50 rows; the Dell's combined position is 7, 9, 17, 24, 24), then the proposal replayed over 141 ESCI judged queries and four reviewed chair controls. Measured: cutoff 75 admits 24 more Exact products (18 better, 0 worse) in one billed rerank unit; `k`=120 admits 5 more (p=0.125); both reproduced on 2026-09-24 |
| Reason (specify a contract) | Support the monitor and wheeled-chair choices; revisit the headphones | Tests for `register_evidence`, then the repair; a claims query (citation extraction given) separating cited evidence from imported reviews and source rating counts; the loop query | The reference repair (must pass) and four faulty variants (each must fail); an independent evidence count; citation mutations; the loop query's zero formula error |

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
- Monitor and chair evidence is thin: the published catalog imports 2 reviews
  for the Dell (6 source ratings) and 1 for the Steelcase (1 rating), and the
  Lab 3 answer typically cites one of each. The Bose control (15 imported
  reviews, 5,341 ratings) provides the sampled-review comparison and is saved
  beside the Lab 3 completion receipt so participants can read its answer.
- A citation checker can reject specific bad inputs without proving every
  natural-language statement true. Participants still read the claim and record.
- The runner reads the query vector the application saved with the search
  event and hands it to `psql`, so participants' direct-method queries and the
  graders reuse the application's vector instead of embedding again. A new
  before or after run embeds afresh, so recall figures vary slightly between
  runs and the guides print none.
- Returned-row count is not recall. Equal counts at two scan settings are
  legitimate; fewer eligible products than the limit is not scan starvation.
- Rank sensitivity shows the formula's behavior, not an optimal parameter.
  Single-request timings include environment and cache effects. Historical
  synthetic-catalog quality numbers are not measurements of this real catalog.

## Pacing and release

The source mission contract remains 10 minutes of introduction, 10 Retrieve,
10 Rank, 20 Reason including completion, and 10 flex. The guides redistribute
time from transcription to diagnosis and proof.

A participant run on 2026-09-24 in a Workshop Studio test account measured the
machine waits and prompted a calibration pass. The recall grader fell from 55 s
to 2–4 s, required reading fell by a quarter to a third per lab, required code blocks
from 51 to 36, written prompts from about 36 to 7, and the manual `EXPLAIN`,
tie-count query and second brief left the required path. Machine waits are now
about 25 s (Lab 1), 30 s (Lab 2) and 3 minutes (Lab 3), plus 40 s for the
completion gate. A model of human reading and writing time still puts a typical
first-time participant over the 40-minute budget and a fast expert near it. A
timed participant run is still required to confirm that the experience fits the
budget; edited time tables are not a rehearsal result.

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
