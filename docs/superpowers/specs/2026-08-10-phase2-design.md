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
- **Aurora only.** No local databases are created for any Phase 2 work.

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
4. Timed `duration_minutes` sum within the **40-minute** lab frame, and
   `session.total_minutes` respects the **45-minute ceiling**.
5. Every retired mission retains every field the eval harness and the GAP
   ledger consume. The check enumerates them explicitly rather than asserting
   "all fields":

   `id`, `stage`, `title`, `query`, `filters`, `target_product_ids`,
   `expected_techniques`, `checkpoint`, `expected_outcome`, `assertions`,
   `top_k`, `duration_minutes`

   Rationale: `docs/intentional-gaps.md` keys GAP-1 and GAP-2 by mission `id`
   and cites `query`, `target_product_ids` and the assertion that turns green;
   `scripts/run_eval.py` consumes `query`, `filters`, `target_product_ids` and
   `top_k`. A retired mission missing any of these silently breaks the harness
   or the ledger.

6. Every assertion named by any mission resolves in `service/assertions.py`
   (already enforced by `tests/test_mission_assertions.py`; the gate calls the
   same code so there is one implementation).
7. Every arm a mission declares in `expected_techniques` has its corresponding
   signal assertion, where one exists. `rank-with-evidence` currently declares
   `hnsw` without asserting `semantic_signal_present` — the same latent hole
   class Phase 1 closed for `fts`.

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
| `exact-identity` | `recover` | Folds into `typo-recovery` as its opening control — the "FTS is fine on an exact model name" baseline that makes the typo failure land. 60 seconds, not a 3-minute exercise. |
| `semantic-eligibility` | `retrieve` | Merges into `rank-with-evidence`, which cannot do RRF without a working semantic arm. Also the mission broken by the refurbished filter. |
| `hnsw-performance` | `optimize` | Already `core: false`. A tuning lab, not a retrieval lab; it needs a benchmark run to say anything honest. Natural self-paced appendix. |

### Lesson coverage — where each surviving lesson attaches

Phase 4 scopes assertions per mission, so every lesson needs a **timed** mission
to attach to. Verified against the contract:

| Lesson | Attaches to | Assertion |
|---|---|---|
| Lexical precision on exact identity | `typo-recovery` (opening control) | `fts_signal_present` |
| Trigram typo recovery | `typo-recovery` | `trigram_signal_present` |
| **Hard-filter eligibility** | `typo-recovery` (`max_price_cents`, `in_stock_only`) **and** `rank-with-evidence` (`in_stock_only`) | `hard_filters_hold` |
| Semantic recall | `rank-with-evidence` (declares `hnsw`) | `semantic_signal_present` — **must be added**, see A1.7 |
| RRF fusion across incomparable scales | `rank-with-evidence` | `rank_provenance_present` |
| Rerank provenance | `rank-with-evidence` | `rerank_score_present` |
| Typed agent tools | `agentic-research` | `retrieval_tool_called` |
| Cited synthesis | `agentic-research` | `citations_present`, `citation_source_revision_present` |
| **Principled abstention** | `agentic-research` (GAP-2: agent must report the gap) | `citations_present` under an unregistered tool |

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
- **Semantic abstention** — the lesson that a semantic arm can recall a product
  the filters must then reject — attaches to `rank-with-evidence` via the same
  added attribute filter, and is asserted by `hard_filters_hold` holding while
  `semantic_signal_present` is non-empty.

### Budget

| Mission | Now (6 missions) | Phase 2 (3 missions) |
|---|---:|---:|
| `typo-recovery` | 8 | **11** |
| `rank-with-evidence` | 10 | **13** |
| `agentic-research` | 10 | **13** |
| **lab total** | 40 | **37** |
| orientation | 2 | 3 |
| scorecard | 5 | 5 |
| **declared `total_minutes`** | 47 | **45** |
| **slack** | **0** | **3** |

The three retired missions contributed 20 minutes (3 + 9 + 8); 17 of those go to
the survivors and 3 become slack, with 1 added to orientation. `orientation 3 +
lab 37 + scorecard 5 = 45`, which meets the 45-minute ceiling exactly with the
slack held inside the lab frame rather than declared as content.

A1.4 checks two things against these numbers: the timed durations sum to at most
the 40-minute lab frame (37 ≤ 40), and `session.total_minutes` is at most 45.

### Sibling repository

The Workshop Studio repository owns participant guides and starter gaps. It is
**not** modified by this phase. What it must change, for the owner to action
there:

- module count 6 → 3, with the retired three presented as a self-paced appendix;
- GAP-1 stays on `typo-recovery`, GAP-2 stays on `agentic-research` — both
  survive, so no gap needs rehoming;
- timings must match `session` in the contract, which is the single source;
- any guide text asserting "six missions" or the retired stage names.

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
`config/`, `db/sql/`, `ui/src/`. SQL function parameter defaults are the one
allowed exception and must be listed explicitly in the check, with a comment
pointing at the yaml, because a Postgres function signature cannot read a file.

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
- The weighted side uses the **ported historical weights** from LOSS-3, not
  numbers tuned for this purpose. The exercise text says so: real provenance
  beats freshly-invented coefficients.
- One diagnostics endpoint returns both orderings for one query.

### Substrate pin

Both functions **must consume identical arm candidate lists** — same per-arm
caps, same per-arm ranks — and differ only in fusion arithmetic. The diagnostics
endpoint asserts this on every call: **same candidate ID set in, different order
out.** If the sets differ, the endpoint fails rather than rendering a comparison
that is really comparing two different candidate pools.

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

### Definition of done

Not "11 files deleted". Every ported consumer produces output **proven
equivalent** to its `catalog.*` predecessor:

1. One **recorded equivalence run** per ported script, with the diff included in
   the implementation report. `run_eval.py` and `benchmark_hnsw.py` feed numbers
   the advanced lane displays; a silent behavior change in the port is forked
   truth's last act.
2. Where equivalence is impossible because the predecessor cannot run at all
   (the `catalog` schema does not exist on the cluster), that is **stated
   explicitly per script** rather than papered over, and the port is validated
   against the live `mosaic_*` tree instead.
3. The deleting commit message references these headers and the loss register,
   closing the loop the in-file deprecation notes opened.
4. No file outside `docs/` references `catalog.` after the deletion.

---

## Exit criteria

1. `make validate-missions` is green, and red when any §1 defect is reintroduced.
2. Three timed missions; three retired with every enumerated field intact.
3. Every lesson in the coverage table attaches to a timed mission.
4. `db/config/retrieval.yaml` is the only file declaring limits, `k`, or
   weights; the tripwire enforces it.
5. `config/workshop.json` is deleted, its weights ported by key name.
6. Both fusion functions consume identical candidate lists, asserted per call.
7. `sql/` is gone; every ported consumer has a recorded equivalence run.
8. `make test`, `npm test`, `npm run build` green; no new lint findings.
9. `main` bootable at every commit.

## Out of scope

Restoring the per-token trigram pipeline (LOSS-2) — recorded as a deliberate
decision, not forgotten. `search_trigram`'s ~1.34 s latency at 500K rows. Mission
control, honesty enforcement, and the advanced lane are Phase 3. Behavioral
assertions are Phase 4.
