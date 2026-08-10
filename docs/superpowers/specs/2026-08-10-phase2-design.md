# Phase 2 — Make the contract the truth

Phase 1 stopped the bleeding. Phase 2 removes the conditions that allowed those
defects to ship: data nobody validates, numbers declared in more than one place,
and a dead schema tree that still teaches.

Baseline `77f34a8`. Every measurement was taken against the live
500,000-product Aurora PostgreSQL 18.3 cluster (`mosaic_catalog`), read-only
unless stated. The rewrite loss register is `docs/rewrite-losses.md`; this spec
cites it rather than restating it.

## Ground rules

- **Ordering is A → B → C → D → E.** Each unit is guarded by the one before it.
- **`main` only, and `main` stays bootable.** One numbered item per commit,
  subject prefixed with the unit (`2A: mission contract gate`).
- **Spec first.** No implementation until this document and the exercise-merge
  detail are confirmed.
- **A gate that cannot check must fail loudly.** `CANNOT VERIFY` is a non-zero
  exit in CI-with-DSN mode. Silent skipping is how the two broken missions in
  §1 survived; the existing live tests skip when `TEST_DATABASE_URL` is unset.
- **Aurora only, now a standing policy.** No local databases exist or will
  exist. The `us-east-1` cluster holds the only live tree; the snapshot is the
  only restore path; every `make` bootstrap target points at Aurora. Recorded in
  `ARTIFACTS.md` and `AGENTS.md`. This stopped being a preference when the two
  local `catalog.*` databases were found dropped, taking Unit E's equivalence
  baseline with them.
- **House standards are binding for gates and probes** (`docs/house-standards.md`):
  errors name the rule/value/fix; every assertion declares a falsifier; probes run
  the production path; a green check is not evidence at birth; an exemption is a
  monitored seam.
- **Timing: 40 nominal, 45 ceiling, buffer never programmed.** Orientation, the
  three exercises and the scorecard all fit inside 40. The 40-to-45 band stays
  empty so a throttled model call or a question-heavy room has somewhere to go.
  When something must be trimmed, orientation and the scorecard go first and
  exercise minutes second; exercise core beats are protected.
- **The run-of-show custody record is the lesson-coverage table** in Unit B. It
  is the authority on which lesson belongs to which mission, and it carries the
  deliberate-loss row explicitly, because a recorded loss is one nobody
  re-litigates.
- **`declares ⇒ asserts`.** A mission that names an arm must assert that arm.
  Enforced by A1.7; see that check for why the rule is total rather than
  case-by-case.
- **Every assertion states how it can fail.** A falsifier is a required field of
  the assertion vocabulary, not a comment. An assertion whose failure condition
  cannot occur reads as evidence while proving nothing, which is the defect
  Phase 1 and Phase 2 both exist to remove. Enforced by A1.8 and by the
  `Assertion` dataclass, which refuses to construct one.
- **Gate error style.** Every failure names the rule, shows the offending value,
  and suggests the nearest fix. `A2.10`'s "did you mean `usb_c_power_w`?" is the
  exemplar; the `explain` helper applies it to every A1 and A2 message.
- **Division of labor.** The gate covers contract-internal consistency and
  contract-versus-Aurora truth. **Lesson coverage and custody remain the
  table's job.** The missing JSONB attribute filter was invisible to the gate
  **by design, not by defect**: no contract-internal rule is broken by a lesson
  going unowned, and a gate that derived pedagogical expectations from the
  contract it judges could not fail — the exact self-reference trap this phase
  removes elsewhere.

## What Phase 2 fixes, measured

Three findings from the read-only survey, all reproducible:

**Two of six missions cannot pass on the live cluster.** Their targets fail
their own declared filters, so `target_in_top_k` and `hard_filters_hold` cannot
both hold:

| Mission | Target | Why it fails |
|---|---:|---|
| `semantic-eligibility` | 234001 | `is_refurbished = true`; `matches_filters` excludes refurbished unless `include_refurbished` is set, which the mission does not set |
| `hnsw-performance` | 420001 | filters on `attributes.usb_c`; the product's actual key is `usb_c_power_w`, so the predicate can never match |

**No gate can catch that.** `make validate` reads a different file
(`data/evals/queries.jsonl`), and `scripts/catalog_contract.py`
reimplements filter logic by hand — it does not know `max_price_cents`,
`in_stock_only`, or the refurbished and sponsored exclusions that the real SQL
`mosaic_search.matches_filters` applies. The mission contract is never checked
against the live schema at all. This is the same shape as Phase 1's missing
`fts_signal_present`: a gate that cannot fail.

**`db/config/retrieval.yaml` is never parsed by anything.** It is a
documentation file. `service/models.py` (`RetrievalProfile` defaults) and
`service/config.py` (`_bounded` defaults) hand-copy its numbers, and
`config/workshop.json` holds a third, *disagreeing* copy with zero consumers
(LOSS-3). The three live copies agree today by luck.

---

## Unit A — the mission contract gate

A new module, `scripts/mission_contract.py`, is the only thing that validates
`data/evals/mosaic_labs_missions.json`. It replaces hand-reimplemented filter
logic for mission checking and runs as `make validate-missions`.

### A1 — shape checks (no database required)

These guard Unit B, which is otherwise unguarded, and they land **before** B
edits anything:

1. Exactly **3** missions in the timed list.
2. The timed and retired lists are **disjoint** — no mission in both, every
   mission in exactly one.
3. The `MosaicLabStage` union in `ui/src/labMissions.ts` covers the stages of
   **both** lists. No orphan stage: no union member unused by any mission, and
   no mission stage missing from the union.
4. **The budget fits inside 40 nominal and does not program the ceiling.**
   Three sub-checks, because "respects the ceiling" is what let the first draft
   through:
   - timed `duration_minutes` sum ≤ the 40-minute lab frame;
   - `orientation_minutes + Σ timed durations + scorecard_minutes ≤ 40`;
   - `session.total_minutes ≤ 40`, **strictly less than the 45 ceiling**, so the
     40-to-45 band is provably unallocated.

   A declared total of exactly 45 is a failure, not a pass. That is the
   distinction the first draft of this spec got wrong.
5. Every retired mission retains every field the eval harness and the GAP
   ledger consume. The check enumerates them explicitly rather than asserting
   "all fields":

   `id`, `stage`, `title`, `query`, `filters`, `target_product_ids`,
   `expected_techniques`, `checkpoint`, `expected_outcome`, `assertions`,
   `top_k`, `duration_minutes`

   Rationale: `ui/src/labMissions.ts` types all twelve, and the retrieval lab
   renders a self-paced mission from the same record as a timed one, so a
   missing field is a broken surface rather than a tidier file.
   `docs/intentional-gaps.md` keys GAP-1 and GAP-2 by mission `id` and cites
   `query`, `target_product_ids` and the assertion that turns green.

   Correction to an earlier draft of this spec, which cited
   `scripts/run_eval.py` as a consumer: it is not one. It reads
   `data/evals/queries.jsonl` against the dead `catalog.*` tree and never opens
   the mission contract. The enumeration is still right; the justification for
   four of its entries was wrong, and a rule defended by a false reason is one
   nobody can check. Unit E ports that script.

6. Every assertion named by any mission resolves in `service/assertions.py`
   (already enforced by `tests/test_mission_assertions.py`; the gate calls the
   same code so there is one implementation).
7. **`declares ⇒ asserts`.** For every arm a mission names in
   `expected_techniques`, that mission must also carry the arm's signal
   assertion. Not "where convenient" — the rule is total over the arms that
   have a signal assertion (`fts`, `pg_trgm`, `hnsw`), and adding a new arm to
   `SIGNAL_ASSERTIONS` extends the rule automatically.

   This generalizes a hole found twice. Phase 1 closed it for `fts`: four of six
   missions lost the lexical arm and every gate stayed green because no
   assertion named it. Phase 2 anticipated one further instance in `hnsw`
   (`rank-with-evidence`). **The gate found five.** The worked example was right
   about the shape and wrong about the count, which is the argument for a total
   rule rather than a case-by-case sweep: hand-enumeration had already missed
   four of the five it was enumerating.

   The converse is deliberately **not** checked. A mission may assert an arm it
   does not declare — that is a stricter promise, not a contradiction.

8. **Every assertion in the vocabulary declares a falsifier.** Checked against
   `service/assertions.py`, where the falsifier is a required dataclass field
   rather than prose. An assertion that cannot fail is decoration that reads as
   evidence.

### A1 numbering note

`A1.8` (falsifiers) was added during Unit B, when the falsifier field became a
house standard. The live checks keep their original numbers `A2.8`–`A2.10`; the
A1 and A2 series are independent, so the repeated `8` is not a collision.

### A2 — live checks (database required)

8. Every target in **both** lists resolves in `mosaic.product`.
9. Every target satisfies its own filters, evaluated by calling
   `mosaic_search.matches_filters(d, f)` on the cluster. Not a reimplementation.
10. Every `filters.attributes` key exists on the target product's `attributes`
    JSONB. This is what would have caught `hnsw-performance`'s `usb_c`.

### Failure modes

- Shape check fails → non-zero, names the mission and the rule.
- No DSN, `MISSION_GATE_REQUIRE_DB=1` (CI-with-DSN mode) → **`CANNOT VERIFY`,
  non-zero**.
- No DSN, flag unset → shape checks run, live checks print `CANNOT VERIFY` as a
  warning, exit zero. Local development stays usable; CI cannot be fooled.

### Verification

- Both §1 defects are reported by A2 before any fix, naming target and cause.
- Reverting either fix turns the gate red again.
- Deleting a required field from a retired mission turns A1.5 red.
- Adding a fourth timed mission turns A1.1 red.
- Unsetting the DSN with the CI flag set exits non-zero with `CANNOT VERIFY`.

### First contact: expected red until B

Unit A ran on the contract as it stood and reported **11 failures / 31 passes**.
Three of those rules were red **by design**, because they encode the shape Unit B
had not yet produced. They are bookkeeping, not open defects:

| Rule | First-contact value | Cleared by | Status at end of B |
|---|---|---|---|
| `A1.1` | 5 timed missions, expected 3 | the 3-exercise cut | green |
| `A1.4b` | `2 + 40 + 5 = 47` vs 40 nominal | the re-derived budget | green |
| `A1.4c` | `total_minutes` 47, must be ≤ 40 | the re-derived budget | green |

The remaining 8 were genuine defects in shipped data: five `A1.7` holes, two
`A2.9` target/filter conflicts, and one `A2.10` wrong attribute key. **A1.7
found five where this spec anticipated one** — see the enumeration in Unit B.

Nobody should read the first-contact report as 11 open defects. Its value was
that a gate written before the data it judges caught both classes at once, and
distinguished them.

---

## Unit B — three timed exercises

Six exercises in 40 minutes averages 6.7 minutes each, and the current budget
is 47 minutes of content in a 47-minute session: **zero slack** for
transitions, questions, or a throttled Bedrock call. Three exercises, each with
room to land, replace six that are rushed.

**Nothing is deleted.** The three retired missions keep their full records in a
`self_paced` list in the same file, exactly as Phase 1 retired the MCP
checkpoint. The eval harness and the GAP ledger continue to resolve them.

### Which three survive

| Mission | Stage | Why it survives |
|---|---|---|
| `typo-recovery` | `recover` | The only exercise where the *failure* is the lesson: FTS returns nothing on an all-misspelled query, trigram recovers the exact product. Owns GAP-1, the repair checkpoint the sibling repo depends on. |
| `rank-with-evidence` | `rank` | The workshop's thesis in one exercise: three arms with incomparable score scales, fused by reciprocal rank, reranked, with per-candidate provenance to inspect. |
| `agentic-research` | `reason` | The "agentic" in the repository name. Owns GAP-2, where the unregistered tool forces the agent to report the gap rather than answer from memory. |

### Which three retire to self-paced

| Mission | Stage | Where its content goes |
|---|---|---|
| `exact-identity` | `recover` | Folds into `typo-recovery` as its opening control — the "FTS is fine on an exact model name" baseline that makes the typo failure land. 60 seconds, not a 3-minute exercise. Asserted under `typo-recovery`'s existing `fts_signal_present`; no new assertion. |
| `semantic-eligibility` | `retrieve` | Merges into `rank-with-evidence`, which cannot do RRF without a working semantic arm. Also the mission broken by the refurbished filter. |
| `hnsw-performance` | `optimize` | Already `core: false`. A tuning lab, not a retrieval lab; it needs a benchmark run to say anything honest. Natural self-paced appendix. |

### The self-paced list ships green

**Both broken missions are repaired in Unit B.** Retiring is not fixing, and a
broken self-paced exercise is worse than a broken timed one: self-paced content
fails **alone**. There is no floor team, no instructor to reframe it, and no
recovery path — the participant simply concludes the system does not work. The
honesty doctrine does not stop at the 40-minute mark.

Both are data-level fixes, verified by the Unit A gate against Aurora. Neither
is a retrieval change; both correct hand-maintained mission data that drifted
from the generated catalog.

**`semantic-eligibility` — target swapped 234001 → 234002.** Two repairs were
measured end to end before choosing, because A2.9 only proves a target satisfies
its filters, not that it is *retrievable*:

| Option | Gate | Target rank (fts / trgm / hnsw) | Reranked position | Verdict |
|---|---|---|---:|---|
| add `include_refurbished: true`, keep 234001 | green | 1 / 2 / 5 | 5 of 10 | **rejected** |
| swap target to 234002, filters unchanged | green | 1 / 1 / 4 | 7 of 10 | **chosen** |

Both pass. The first was rejected on meaning, not mechanics: this mission's
entire subject is that eligibility outranks similarity, and setting
`include_refurbished` to make the target legal deletes the constraint the lesson
is about. 234002 is a non-refurbished sibling — same carbon-plate racing shoe,
$189.99 against $219.99 — so the mission keeps its filters and gains a target
that satisfies them honestly.

The swap also makes the lesson sharper than the original. Under the mission's own
filters, 234001 is not merely ranked below 234002 — **it is not a candidate at
all**: `matches_filters` runs *inside* each arm, so the refurbished sibling is
excluded before scoring. Measured: zero rows visible to any arm. Eligibility is
not a re-ranking, it is a gate, and the near-identical excluded sibling is what
makes that visible.

**`hnsw-performance` — attribute key corrected `usb_c` → `usb_c_power_w: 90`.**
One correction to this spec's §1 claim: `usb_c` does **not** fail universally.
4,215 products carry `usb_c` and match the predicate — the target simply is not
one of them, because it stores the wattage under `usb_c_power_w`. The predicate
was answerable and wrong, which is worse than unsatisfiable and obvious: the
mission returned a full pool of 50 candidates and never its own target. Measured
after the fix: eligible pool 3,032 products, target reranked to **position 1**.

Exit condition: **every mission in the self-paced list is green under the Unit A
gate**, on the same terms as the timed three.

### The five `A1.7` violations, resolved as decisions

The spec anticipated one; the gate found five. Each was resolved by measuring the
arm alone under the mission's own filters — never by symmetry. Two measurement
notes matter:

- Arm-alone pools must be taken **after `mosaic_search.configure_hnsw`**. A first
  pass that skipped it reported semantic pools of 0–38 against a 150 cap; those
  numbers were an artefact of default iterative-scan limits, not of the arm. Re-run
  correctly, the same pools are 150.
- `semantic_in_pool > 0` only proves the arm reached the fused pool. The sharper
  question — does the arm recall *this mission's target* — is what decided the two
  open cases.

| Mission | Arm | Measured (arm alone, under the mission's final filters) | Resolution |
|---|---|---|---|
| `rank-with-evidence` | `pg_trgm` | pool **2**, target **rank 2** | **ASSERT** |
| `rank-with-evidence` | `hnsw` | pool 150, target **rank 3** | **ASSERT** |
| `hnsw-performance` | `hnsw` | pool 150 after repair, target reranked **1** | **ASSERT** |
| `agentic-research` | `hnsw` | pool 150, targets **not recalled** by any single arm | **ASSERT** |
| `typo-recovery` | `hnsw` | pool 150, target **not recalled**; fts 1, trgm 1 | **UN-DECLARE** |

**`rank-with-evidence`: assert both, as predicted.** Trigram is its lesson and
HNSW feeds its fusion comparison; both recall the target in the top three when
run alone, so both assertions are live rather than decorative. The mission also
gained `fts` explicitly — it was already receiving the lexical arm (pool 120,
target rank 2) and now declares and asserts it.

One measured consequence of adding the attribute filter, recorded because it cuts
against the change: **the trigram pool falls from 80 to 2.** Eligibility is
applied inside the arm, so `seat_depth_adjustable: true` shrinks what trigram has
to match against. The assertion still holds — 2 candidates, target at rank 2 —
and `trigram_in_pool` is 2 of the 50 fused slots. It is thin, and thin on purpose
is still thin: this is the arm most likely to be the first to fail if the catalog
is reseeded with different attribute coverage. Flagged for Phase 4, which owns
behavioral thresholds; a pool-size floor is not in Phase 2's scope and inventing
one here would be an unmeasured number in a spec that has been rejecting those.

**`hnsw-performance`: assert semantic**, its own subject. The measured trigram
must-abstain is kept as-is: pool 0 on a clean, correctly-spelled query, and the
mission does not declare `pg_trgm`, so nothing asserts it. That is the abstention
rule working, not a gap.

**`agentic-research`: ASSERT, against the weaker reading of the evidence.** No
single arm recalls its targets — the fused-and-reranked run returns 429001, and
370001 arrives through fusion rather than any one arm. The semantic pool is
nonetheless 150 of 150, and the mission's answer is synthesized from the fused
pool that the vector arm dominates (22 of 50 fused slots). A dead vector arm here
would not produce a wrong rank; it would produce a *differently-sourced answer*
with citations that still look valid — the failure mode this mission exists to
make visible. Asserted.

**`typo-recovery`: UN-DECLARE, the one case where the prior was wrong.** Every
term in `wirless noice canceling hedphones` is misspelled. The semantic arm
returns a full 150-row pool but **does not recall the target**; FTS and trigram
each rank it 1. The mission's lesson is precisely that fuzzy matching recovers
what embeddings do not, so declaring `hnsw` claimed a contribution the arm does
not make. Removing it from `expected_techniques` is the honest edit; asserting
`semantic_signal_present` here would have been an assertion that passes on a pool
size while the arm contributes nothing to the outcome. This is the "no assertion
whose failure condition cannot occur" rule catching a would-be decoration.

Net: four ASSERT, one UN-DECLARE. Symmetry would have produced five ASSERTs and
one false claim.

### Lesson coverage — where each surviving lesson attaches

Phase 4 scopes assertions per mission, so every lesson needs a **timed** mission
to attach to. Verified against the contract:

**This is the run-of-show custody record** (amendment 2). It is the authority on
which lesson belongs to which mission, including the row that records a
deliberate loss — recorded losses are the ones that do not get re-litigated.

| Lesson | Custody | Assertion |
|---|---|---|
| Lexical precision on exact identity | `typo-recovery` (opening control, 60s) | `fts_signal_present` (existing) |
| Trigram typo recovery | `typo-recovery` | `trigram_signal_present` |
| **Embeddings do not recover typos** | `typo-recovery` (`hnsw` un-declared on measurement) | none — the arm is not claimed, so nothing asserts it |
| **Hard-filter eligibility** | `typo-recovery` (`max_price_cents`, `in_stock_only`) **and** `rank-with-evidence` (`in_stock_only`) | `hard_filters_hold` |
| **JSONB attribute eligibility** | `rank-with-evidence` (`seat_depth_adjustable`) | `hard_filters_hold` — **filter added** |
| Semantic recall | `rank-with-evidence` (declares `hnsw`) | `semantic_signal_present` — **added**, see A1.7 |
| **Eligibility is a gate, not a re-ranking** | `semantic-eligibility` (self-paced; excluded sibling 234001 is never a candidate) | `hard_filters_hold` with `target_in_top_k` on 234002 |
| RRF fusion across incomparable scales | `rank-with-evidence` | `rank_provenance_present` |
| Rerank provenance | `rank-with-evidence` | `rerank_score_present` |
| Weighted vs unweighted fusion | `rank-with-evidence` (Unit D comparison) | identical-candidate-list assertion |
| Typed agent tools | `agentic-research` | `retrieval_tool_called` |
| Cited synthesis | `agentic-research` | `citations_present`, `citation_source_revision_present` |
| **Principled abstention** | `agentic-research` (GAP-2: agent must report the gap) | `citations_present` under an unregistered tool |
| **Index tuning — DELIBERATE LOSS from the clock** | **advanced lane** (bench harness / measured page), **not** a timed mission | `measurement_configuration_persisted`, `measurement_kind_declared` |

**Custody transfer for the `measurement_*` assertions.** They do not re-home to
a timed mission. They belong to the advanced lane — the benchmark harness and
the measured page — where a number can be produced honestly. Phase 4 attaches
them there, not to the timed three.

The lesson leaves the clock, not the session. The scorecard/close gains one
pointing sentence to that effect: **the operating point is measured, not
guessed, and the self-paced lane measures it on your own cluster.** No timed
minutes are spent on it, and specifically no 4-minute HNSW demo is funded out of
`agentic-research`.

Two lessons need explicit attention because they are at risk of retiring with
their missions:

- **Hard-filter eligibility does not live only in the retired three.** Two
  surviving missions carry hard filters, so the lesson survives. But
  `semantic-eligibility` was the only mission filtering on
  `filters.attributes` (`carbon_plate`). Unit B **adds
  `attributes: {"seat_depth_adjustable": true}` to `rank-with-evidence`** so
  JSONB attribute eligibility stays timed.

  Measured on the live cluster: target 370001 carries
  `seat_depth_adjustable: true`, satisfies the combined filter set
  (`domain`, `in_stock_only`, that attribute), and the eligible pool is 8,976
  products — wide enough that the filter is doing selection rather than
  hand-picking the answer. Use `seat_depth_adjustable`, **not**
  `lumbar_support`: the latter is the string `"Dynamic"` on this product, and
  `matches_filters` compares JSONB containment, so a boolean predicate against
  it would never match. This is the same failure shape as
  `hnsw-performance`'s `usb_c`.
- **Eligibility as a gate rather than a re-ranking.** This spec previously
  described the lesson as "a semantic arm recalls a product the filters must then
  reject". **That is wrong on this codebase**, and correcting it matters because
  the wrong version teaches a wrong mental model. `matches_filters` is called
  *inside* `search_fts`, `search_trigram` and `search_vector`, so an ineligible
  product is never a candidate — there is nothing to reject after the fact.
  Measured: under `semantic-eligibility`'s own filters, the refurbished sibling
  234001 returns zero rows to every arm.

  The lesson keeps its custody and gains a sharper demonstration: two
  near-identical racing shoes, one eligible and one not, where the ineligible one
  never appears at any stage. Asserted by `hard_filters_hold` alongside
  `target_in_top_k` on 234002.

### Budget

**40 nominal, 45 ceiling, buffer never programmed.** Everything — orientation,
the three exercises, the scorecard — fits inside 40. The 40-to-45 band stays
empty. It is there to absorb a throttled Bedrock call or a room that asks
questions, and a plan that spends it has no buffer at all, only a longer
session.

| Mission | Now (6 missions) | Phase 2 (3 missions) |
|---|---:|---:|
| `typo-recovery` | 8 | **11** |
| `rank-with-evidence` | 10 | **12** |
| `agentic-research` | 10 | **11** |
| **lab total** | 28 | **34** |
| orientation | 2 | 2 |
| scorecard | 5 | **4** |
| **declared `total_minutes`** | 47 | **40** |
| **unprogrammed ceiling headroom** | **0** | **5** |

`orientation 2 + lab 34 + scorecard 4 = 40`. The three retired missions
contributed 20 minutes; 6 go to the survivors and the rest leaves the clock.

Trim order was applied as directed — orientation and the scorecard first, the
scorecard giving up a minute before any exercise was touched. Bringing the
budget inside 40 then required more, so **exercises 2 and 3 returned 1 and 2
minutes of their merge gains**: `rank-with-evidence` went 13 → 12 and
`agentic-research` went 13 → 11 against the rejected draft. **Every exercise
still nets positive against its pre-merge duration**:

| Mission | Pre-merge | Rejected draft | Final | Net vs pre-merge |
|---|---:|---:|---:|---:|
| `typo-recovery` | 8 | 11 | **11** | **+3** |
| `rank-with-evidence` | 10 | 13 | **12** | **+2** |
| `agentic-research` | 10 | 13 | **11** | **+1** |

No exercise drops below where it started; two give back part of a gain. Prose
matches arithmetic, on the same terms the board is held to.

A1.4 checks two things: the timed durations sum to at most the 40-minute lab
frame (34 ≤ 40), and `session.total_minutes` is at most 45 — satisfied at 40
with five minutes unallocated.

### The gate's first save, recorded

An earlier draft of this budget was `orientation 3 + lab 37 + scorecard 5 = 45`.
That allocates the hard ceiling: every minute of buffer is programmed as
content, so the first delay pushes the session past 45 with nothing to give.
**A1.4 as written would have rejected it** — 37 exercise-minutes plus 8 of
orientation and scorecard leaves the 40-minute frame with no room, and the
declared total sat exactly on the ceiling rather than under it.

The check therefore caught a real defect before the check existed, in the
document that specifies it. Recorded here because it is the argument for
shape-level gates in one line: the rule found the mistake that the person
writing the rule had just made.

### Sibling repository

The Workshop Studio repository owns participant guides and starter gaps. It is
**not** modified by this phase. What it must change, for the owner to action
there:

- module count 6 → 3, with the retired three presented as a self-paced appendix;
- GAP-1 stays on `typo-recovery`, GAP-2 stays on `agentic-research` — both
  survive, so no gap needs rehoming;
- timings must match `session` in the contract, which is the single source:
  orientation 2, exercises 11/12/11, scorecard 4, total 40;
- any guide text asserting "six missions" or the retired stage names;
- **`semantic-eligibility`'s target changed 234001 → 234002** (Velocity Carbon 3,
  $189.99). Any guide screenshot or expected-result table naming the old product
  is now wrong;
- **`typo-recovery` no longer declares `hnsw`.** Guide text claiming embeddings
  help recover typos contradicts the measurement and should be inverted: on an
  all-misspelled query the semantic arm returns a full pool and does not recall
  the target.

---

## Unit C — one source for retrieval numbers

`scripts/retrieval_profile.py` parses `db/config/retrieval.yaml` and supplies
defaults to `RetrievalProfile` and `Settings`. Environment variables still
override; the yaml stops being decorative. Bounds stay where Phase 1 put them,
next to the setting.

### C1 — the tripwire

A check that **fails if any file other than `db/config/retrieval.yaml` declares
a candidate limit, a fusion `k`, or a weight.** The module fixes today's three
copies; the tripwire prevents the fourth. Scope: `service/`, `scripts/`,
`config/`, `db/sql/`, `db/config/`, `ui/src/`.

**Exemptions are monitored seams, never blind spots.** A PostgreSQL function
signature cannot read a file, so `db/sql/` parameter defaults are exempt from
*declaring*. They are **not** exempt from *agreeing*: each exempted default is
pinned to a yaml field and asserted equal to it. `CREATE INDEX ... WITH (...)`
build parameters are exempt on the same grounds and monitored the same way. An
exemption with no yaml counterpart must carry a written reason, checked by test.

Sixteen defaults and index parameters are pinned. The drift fixtures — a second
declaration, a drifted SQL default, a drifted index parameter — are **permanent
tests** in `tests/test_config_tripwire.py`, not a one-time demonstration.

### C1 findings, recorded

The tripwire reported **9 violations on first contact**, two of which hand
inspection had missed:

- **The yaml disagreed with itself.** `rerank.candidate_limit: 30` sat in the
  file that claims to be the single source and was read by nothing; the code path
  uses `fusion.fused_limit: 50`. Deleted, not reconciled — an unread key is not a
  configuration, it is a fourth copy inside the third.
- **A hardcoded UI fallback.** `ui/src/pages/SearchPage.tsx` rendered
  `k={diagnostics?.rrf_k ?? 60}`. A `??` fallback decides what a participant
  reads, so it is structurally a declaration and the check treats it as one. The
  same line also labelled unweighted RRF as "Weighted RRF"; both fixed.
- The remaining 7 were `config/workshop.json` (6) and the evidence index's
  `ef_construction = 160`, which is exempted with a stated reason: a smaller
  corpus with a different recall target, not part of the product retrieval
  profile.

### C2 — `config/workshop.json` is deleted

Confirmed zero consumers. Its values port **by key name** into
`retrieval.yaml` with a provenance comment, per LOSS-3:

| Key | Value | Disposition |
|---|---:|---|
| `weights.lexical` | 0.30 | ports as a fusion weight |
| `weights.semantic` | 0.45 | ports as a fusion weight |
| `weights.trigram` | 0.10 | ports as a fusion weight |
| `weights.business_signals` | 0.15 | **historical only** — the business signal is a post-fusion nudge capped at 0.05, and 0.15 is the exact value behind the Phase 1 crash |
| `trigram_similarity_threshold` | 0.24 | **stale** — live 0.20 stands, discrepancy recorded, nothing ported |
| candidate limits 100/75/100 | — | **not ported** — live 120/80/150 already in the yaml |

No "sync", no survival: the file is deleted in the same commit that ports its
weights.

### Verification

- Changing a limit in the yaml changes the served profile with no code edit.
- Adding a limit to any other file turns the tripwire red.
- `config/workshop.json` is gone and nothing references it.
- The ported weights round-trip: yaml → profile → the weighted fusion function.

---

## Unit D — weighted RRF as a comparison, not a default

Per-arm weights tuned on three missions would be overfitting presented as
improvement, and the existing eval already shows lexical beating hybrid on a
judged query. So weighted fusion ships as a **runnable side-by-side** inside
exercise 2, not as a behavior change.

- A **new** function, `mosaic_search.search_hybrid_rrf_weighted`, alongside the
  unweighted one. `search_hybrid_rrf` is not modified.
- The weighted side uses the **ported historical weights** from LOSS-3, now living
  in `db/config/retrieval.yaml` under `fusion.weights`, not numbers tuned for this
  purpose. The exercise text says so: real provenance beats freshly-invented
  coefficients.
- One diagnostics endpoint returns both orderings for one query.

### The flip is scheduled, not drifted into

**Default behavior is unchanged in Unit C, and unchanged by Unit D's landing.**
The decision to make weighted fusion the default is deliberately scheduled at
**Unit D's STOP AND REPORT** — after the identical-candidate-list assertion has
proven both functions consume the same pool. Until that report is accepted,
`search_hybrid_rrf` stays the served path.

The reason for pinning it to a named checkpoint: a flip that happens because the
weighted function exists and looks better on one query is exactly the
unmeasured-improvement failure this unit is structured to avoid. The existing eval
already shows lexical beating hybrid on a judged query. Weights tuned on three
missions would be overfitting presented as progress, and the only defence is that
the switch requires an explicit decision at a recorded moment.

This sentence exists so the flip cannot happen by drift. The same note is carried
in `db/config/retrieval.yaml` beside the weights themselves, where anyone about to
consume them will read it.

### Substrate pin

Both functions **must consume identical arm candidate lists** — same per-arm
caps, same per-arm ranks — and differ only in fusion arithmetic. The diagnostics
endpoint asserts this on every call: **same candidate ID set in, different order
out.** If the sets differ, the endpoint fails rather than rendering a comparison
that is really comparing two different candidate pools.

**The assertion must read the untruncated pool.** Both functions apply
`LIMIT result_limit` *after* fusion, so two different orderings truncated at the
same depth necessarily disagree about the tail. Measured on the served 50-row
window: only **36 of 50** in common, `sets_identical` false — against full pools
that were identical at **250**, each exactly equal to the arm union. Comparing the
served windows would have failed a healthy substrate on every call. Hence
`FULL_POOL_LIMIT`, which must exceed the summed arm caps (120 + 80 + 150 = 350).

Measured across all six missions at full depth: **candidate sets identical on
6 of 6**, pools 152–342, orders differ on 6 of 6.

### Two deployment hazards found while landing this

**`CREATE OR REPLACE` cannot change a signature — it creates an overload.**
Adding `trigram_threshold` to `search_hybrid_rrf` left **two** live functions on
Aurora, and a caller passing nine positional arguments would silently bind the old
body. The stale signature is now dropped explicitly by a `DROP FUNCTION IF EXISTS`
above the `CREATE OR REPLACE`, so the replacement is a replacement.

**Whole-file replay of `09_search_functions.sql` now fails.** `SET
pg_trgm.similarity_threshold` inside `search_trigram` needs a privilege
`retrieval_admin` no longer holds; the function is already live with the correct
`proconfig`. Apply only the changed functions rather than loosening a grant to
re-apply identical SQL.

### The trigram threshold stops being a positional literal

`search_hybrid_rrf` called `search_trigram(q, f, trigram_limit, 0.20)`. A
**positional** literal is invisible to the Unit C tripwire, whose rule 1 only
matches assignment-shaped declarations. It is now a named parameter on both fusion
functions, threaded from `candidate_generation.trigram_threshold` and pinned by the
tripwire — so the value cannot diverge between the two functions, which is
precisely what the substrate assertion depends on.

This exposed a second hole: `name type DEFAULT value` has no `=` or `:` either, so
**rule 1 could not see any SQL parameter default**, and rule 2 only checked the
ones already listed. Unit D added 13 defaults — three of them fusion weights — and
**the tripwire stayed green with none of them pinned**. New rule `C1c` requires
every retrieval-named SQL default to be enumerated; pinned count went 16 → 26.

### MATERIALIZED

LOSS-4 is **closed**: the three arms are `LANGUAGE sql` functions and therefore
optimization fences, so per-arm caps hold in the chosen plan and no
`MATERIALIZED` hint is required. Re-verified structurally against the live
cluster. The weighted function is also a `LANGUAGE sql` function over the same
three arm functions, so it inherits the verdict from birth — and the endpoint's
identical-candidate-list assertion re-proves the substrate continuously rather
than trusting the record.

### Verification

- Identical candidate ID sets from both functions on every mission query.
- The orderings differ on at least one mission query, or the comparison teaches
  nothing and the exercise says so honestly.
- Default `POST /api/search` behavior is byte-identical before and after Unit D.

---

## Unit E — delete the `catalog.*` tree

The tree is **11 files** in `sql/`, not 10: `08_benchmark_schema.sql` defines
`catalog_bench` and was missing from earlier counts. All 11 now carry in-file
deprecation headers (commit `77f34a8`).

Consumers to port or delete: `scripts/run_eval.py`,
`scripts/benchmark_hnsw.py`, `scripts/load_catalog.py`,
`scripts/load_media.py`, `tests/test_sql_integration.py`, and one stale
reference in `ui/src/showcase.test.ts`.

### Substrate verdict — equivalence is impossible

Checked before Unit C proceeded, and it invalidated this unit's original
definition of done. **`catalog_workshop` and `catalog_codex_20260807` do not
exist**, live Aurora has no `catalog` schema, and no dump, archive, or committed
golden output exists anywhere in the tree. The DDL survives in git; the loaded
state — 500,000 rows with real Cohere embeddings — does not, and the embedding
cache is keyed to the `mosaic_*` projection.

So "diff the port against its predecessor" is unavailable for **all six**
consumers. Rebuilding a baseline was considered and rejected: it resurrects a
deliberately deprecated tree onto the live cluster, and at reduced scale the
latency numbers would not transfer, buying a baseline that is not the real
baseline. Full evidence, the reconciled 11-file inventory, and the per-consumer
case table are recorded as SUBSTRATE-1 in `docs/rewrite-losses.md`.

### Definition of done — correctness, replacing equivalence

Not "11 files deleted", and no longer "proven equivalent":

1. **Per script, a recorded correctness statement against live `mosaic_*`**: what
   it now produces, why that output is right by named checks rather than
   assertion, and the explicit line *"no predecessor comparison possible — both
   `catalog.*` databases dropped 2026-08; DDL survives in git, loaded state does
   not."*
2. **The no-baseline risk is mitigated per script, by name.** For
   `run_eval.py`, correctness is the golden missions' expected targets: the
   contract gate's A2 checks are the baseline that *does* exist. For the two
   loaders, correctness is a superseded-by pointer to the `mosaic_*` path plus
   deletion. For the tests, retarget-or-delete with the reason stated.
3. **`benchmark_hnsw.py` is A-MINIMAL**: ported to run against `mosaic_*`,
   connectivity proven, and its **output contract explicitly deferred** to Phase
   3's advanced-lane spec (`bench.runs` shape, ground-truth recall definition).
   One sentence in the disposition record, so Phase 3 finds it waiting rather
   than broken.
4. **The five latent local-Postgres targets are resolved**: `db-init`,
   `db-load`, `db-load-catalog`, `db-load-media`, `db-index` currently install or
   read the dead tree against whatever DSN they are handed. Retarget to `mosaic_*`
   equivalents or delete, per consumer disposition. `config/.env.example` and two
   `README.md` `localhost` examples go the same way, per the Aurora-only policy in
   `ARTIFACTS.md`.
5. The deleting commit message references the in-file headers and the register,
   closing the loop the deprecation notes opened.
6. No file outside `docs/` references `catalog.` after the deletion.

---

## Exit criteria

1. `make validate-missions` is green, and red when any §1 defect is reintroduced.
2. Three timed missions; three retired with every enumerated field intact.
3. Every lesson in the custody table sits with its recorded owner — the timed
   missions for the retrieval and agent lessons, the advanced lane for the
   `measurement_*` pair. The deliberate-loss row is present and unchanged.
4. **Every mission in the self-paced list is green under the gate**, on the same
   terms as the timed three. No exercise ships broken to a lane where the
   participant is alone.
5. **`declares ⇒ asserts` holds for every mission in both lists**, and adding an
   arm without its assertion turns the gate red. All five violations found at
   first contact are resolved individually, each ASSERT with a stated falsifier
   and each UN-DECLARE with a measured reason.
6. **Every assertion in the vocabulary declares a falsifier**, enforced by A1.8
   and by the dataclass that refuses to build one without it.
7. **The declared budget is 40 nominal with the 40-to-45 band unallocated.**
   `session.total_minutes` is 40; A1.4 rejects a budget that programs the
   ceiling, as it would have rejected this spec's first draft.
8. **Every gate failure names the rule, the offending value, and a fix.**
9. `db/config/retrieval.yaml` is the only file declaring limits, `k`, or
   weights; the tripwire enforces it.
10. `config/workshop.json` is deleted, its weights ported by key name.
11. Both fusion functions consume identical candidate lists, asserted per call.
12. `sql/` is gone; every ported consumer has a recorded equivalence run.
13. `make test`, `npm test`, `npm run build` green; no new lint findings.
14. `main` bootable at every commit.

## Out of scope

Restoring the per-token trigram pipeline (LOSS-2) — recorded as a deliberate
decision, not forgotten. `search_trigram`'s ~1.34 s latency at 500K rows. Mission
control, honesty enforcement, and the advanced lane are Phase 3. Behavioral
assertions are Phase 4.
