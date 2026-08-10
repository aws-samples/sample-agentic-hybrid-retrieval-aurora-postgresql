# Truth register

Append-only. Facts about this system that would otherwise live only in
conversation: capabilities lost in the rewrite from `catalog.*` to `mosaic_*`,
measurement questions the rewrite raised, and claims the codebase made that
turned out to be false.

**Charter widened 2026-08-10, recorded rather than done silently.** The file was
"rewrite loss register". LOSS-5 does not fit that title — it is not a lost
capability but an arm a mission *claimed* and never had, so nothing was lost
because nothing was ever there. The two candidate placements were a separate
corrections section or a wider charter. Wider charter, because the file's actual
function was never "losses": it is the record of things that a later session
could not otherwise cite, and every entry already answers the same three
questions. A corrections section would have created a placement argument for
every future entry and split the `LOSS-n` numbering that other documents cite. The
`LOSS-` prefix is kept for exactly that reason — the identifiers are referenced
from `docs/superpowers/specs/`, `db/config/retrieval.yaml`, and commit messages,
and renaming them to buy a tidier title would break more than it fixes.

Every entry states the substance, the evidence, and **what would have caught
it** — because in nearly every case the answer is an assertion or a gate that did
not exist.

Entries are never edited to hide a mistake. Corrections are appended to the
entry with a date.

All measurements below were taken against the live 500,000-product Aurora
PostgreSQL 18.3 cluster (`mosaic_catalog`), read-only unless stated. There is no
local database; see `ARTIFACTS.md`.

---

## LOSS-1 — FTS OR-combine and strict-AND bonus

**Dropped.** `catalog.search_lexical` (`sql/04_search_functions.sql`) built two
tsqueries: a `broad_tsq` of OR-combined lexemes for recall, and the strict
`websearch_to_tsquery` retained as a `+1.0` scoring bonus. The rewritten
`mosaic_search.search_fts` built only the strict form, which ANDs every term.

**Consequence.** A conversational query requires every token to appear in one
document; a misspelled token appears in none, so the conjunction is
unsatisfiable and the arm returned zero rows. Measured on the live cluster
before the fix, **four of the six missions** received an empty lexical arm —
`typo-recovery`, `semantic-eligibility`, `rank-with-evidence` and
`agentic-research`. Two of those declare `fts` in `expected_techniques`, making
them contract violations; the other two recovered as a side effect.

Note on scope: an earlier account of this loss said five of six. The measured
number is four of six — `exact-identity` (1 row) and `hnsw-performance` (1 row)
both retained a lexical arm under the shipped builder.

**Fixed** in Phase 1, commit `dbb3c30`, in `db/sql/09_search_functions.sql`.
Exact identity still holds rank 1 with a 2.52x score gap over the runner-up, so
the strict bonus does its job. A negation guard was required: `tsvector_to_array`
discards `NOT`, so a naive OR-combine inverts a user's exclusion.

**What would have caught it.** A mission-scoped assertion naming the lexical
arm. None existed; `fts_signal_present` was added in the same phase
(`service/assertions.py`) and is proven to go red against the shipped function
and green against the fix.

---

## LOSS-2 — per-token trigram pipeline

**Dropped, still absent.** `catalog.search_trigram` combined two scoring paths
in a `UNION ALL` and took the per-product `max`:

- `whole_query` — `greatest(similarity, word_similarity)` over the whole query
  string;
- `token_query` — a `tokens AS MATERIALIZED` CTE splitting the query on
  non-alphanumerics and keeping tokens of length >= 4, then per product
  `max(word_similarity(token, trigram_text))` plus a `0.04` multi-token bonus,
  gated by a `HAVING` coverage rule requiring at least 2 distinct matching
  tokens once the query has 4 or more.

The rewritten `mosaic_search.search_trigram` keeps only a whole-string form:
`greatest(similarity, word_similarity, strict_word_similarity)`. There is no
token CTE, no coverage rule, and no multi-token bonus.

**Measured effect on scores.** Per-token scoring is dramatically stronger on
exactly the misspelled multi-word queries the workshop uses. Target is each
mission's own target product:

| Query | Target | Live whole-string | Per-token max |
|---|---:|---:|---:|
| `wirless noice canceling hedphones under $200 with long batery life` | 2 | 0.797 | 1.000 |
| `ergonmic mesh chiar for long workdays with adjustable lumbar support` | 370001 | 0.402 | 1.000 |
| `carbon plated marathon shoe under $220 with stable cornering` | 234001 | 0.407 | 1.000 |
| `quiet mechancial keybaord` | 429001 | 1.000 | 1.000 |
| `noice canceling hedphones` | 2 | 0.893 | 1.000 |

**Consequence, stated honestly.** Every one of those live scores clears the
`0.20` floor, and the live arm ranks the target 1st or 2nd on four of the five
queries. So the dropped pipeline is a **real loss of headroom, not a live
retrieval failure** on the current mission set. Phase 1's addition of
`strict_word_similarity` to the `greatest()` recovered much of the practical
gap.

Correction recorded 2026-08-10: this entry initially attributed the absence of
target 234001 from the live trigram pool to per-token scoring. That was wrong.
`mosaic_search.search_trigram` applies `matches_filters(d, f)` even when
`f = '{}'`, and the default excludes refurbished products; 234001 is
`is_refurbished = true`. With `include_refurbished` the target returns at rank
2, score 0.407. The cause is the refurbished default, tracked as a mission-data
defect in the Phase 2 spec, not a scoring loss. Earlier figures of 0.160
whole-string and 0.583 per-token are not reproducible against this cluster; the
measured values are in the table above.

**What would have caught it.** Nothing in this repository compares arm quality
between the two trees, and no assertion measures *rank headroom* as opposed to
mere presence. A per-arm recall check against a small labelled set would have.
Restoring the pipeline is not Phase 2 scope; it is recorded here so the decision
is deliberate rather than forgotten.

**Note, and the best short argument for `declares ⇒ asserts`.** The mission that
*taught* attribute eligibility, `semantic-eligibility`, is the mission *broken by*
attribute eligibility: its target is `is_refurbished = true`, which the default
filter excludes, so the exercise demonstrating that filters are load-bearing
could not itself pass its filters. It declared `hnsw` and `fts` and asserted
neither arm's signal for most of its life. A contract rule requiring every
declared arm to be asserted is the cheapest thing that would have surfaced it.

Resolution recorded 2026-08-10 (Phase 2 Unit B): the mission's target moved
234001 → **234002**, a non-refurbished sibling of the same carbon-plate racing
shoe, and its filters were left untouched. The rejected alternative was adding
`include_refurbished: true`, which also turns the gate green — and deletes the
constraint the lesson is about. Rows above that cite 234001 as this mission's
target are historical; the trigram measurement itself is unaffected, since it was
taken on the product rather than on the mission.

The irony has a second half worth recording. The repaired mission is now a
*better* demonstration than the original, because measuring the repair exposed
something the original framing had wrong: `matches_filters` is evaluated **inside**
each arm, so an ineligible product is never a candidate at all — measured at zero
rows visible to any arm for 234001 under the mission's own filters. Eligibility is
a gate, not a post-hoc rejection. An earlier draft of the Phase 2 spec described
this lesson as "the semantic arm recalls a product the filters must then reject",
which is a wrong mental model of this codebase; the near-identical excluded
sibling is what makes the real behavior visible.

---

## LOSS-3 — per-arm fusion weights

**Dropped.** The pre-rewrite configuration carried explicit per-arm fusion
weights. `config/workshop.json` is their only surviving record, and **nothing in
the repository reads that file** — no Python, TypeScript, Makefile target, or
doc. RRF shipped unweighted: `mosaic_search.search_hybrid_rrf` gives every arm
`1.0 / (rrf_k + rank)` with no coefficient.

The values, ported **by key name** from `config/workshop.json`:

| Key | Value | Disposition |
|---|---:|---|
| `weights.lexical` | 0.30 | ports to `retrieval.yaml` as a fusion weight |
| `weights.semantic` | 0.45 | ports to `retrieval.yaml` as a fusion weight |
| `weights.trigram` | 0.10 | ports to `retrieval.yaml` as a fusion weight |
| `weights.business_signals` | 0.15 | **historical only, does not enter fusion** |
| `trigram_similarity_threshold` | 0.24 | **stale, ports nothing** |

`business_signals: 0.15` does not become a fusion weight. Standing decision: the
business signal is a post-fusion nudge, hard-capped at `0.05`. That 0.15 is the
exact value behind the Phase 1 crash — `config/.env.example` shipped
`BUSINESS_WEIGHT=0.15` against a `le=0.05` bound, and every search returned an
unhandled HTTP 500. It is recorded here as history, not configuration.

`trigram_similarity_threshold: 0.24` is stale. The live default is `0.20`
(`mosaic_search.search_trigram`), and `0.20` stands. The discrepancy is recorded;
nothing is ported.

The same file's candidate limits also disagree with the live system — 100/75/100
against the live 120/80/150. They are not ported either; `retrieval.yaml`
already holds the live values.

**What would have caught it.** A tripwire forbidding any file other than
`db/config/retrieval.yaml` from declaring limits, fusion `k`, or weights. Phase 2
Unit C adds it. Without one, a fourth copy is inevitable — there were three when
Phase 2 began, agreeing only by luck.

**Resolved 2026-08-10, Phase 2 Unit C.** `scripts/retrieval_profile.py` now parses
the yaml and supplies every retrieval number to `service/config.py` and
`service/models.py`; no default is restated in code, and a missing key is a named
startup failure rather than a silent fallback. The three weights above are ported
**by key name** into `fusion.weights`. `business_signals: 0.15` is not ported and
never enters fusion; `trigram_similarity_threshold: 0.24` is not ported and the
live `0.20` is now *declared* in the yaml as `candidate_generation.trigram_threshold`
and asserted equal to the SQL literal. `config/workshop.json` is deleted.

`scripts/config_tripwire.py` enforces the rule and was proven red at birth on all
three of its failure modes: a second declaration, a drifted SQL parameter default,
and a drifted index build parameter. The fixtures are permanent tests in
`tests/test_config_tripwire.py`, not a one-time demonstration.

Two findings the tripwire produced that hand inspection had missed. First, the
yaml *itself* carried a fourth disagreeing copy: `rerank.candidate_limit: 30`,
read by nothing, while the code path uses `fusion.fused_limit: 50`. The file that
claimed to be the single source disagreed with itself, and the unread key is
deleted rather than reconciled. Second, `ui/src/pages/SearchPage.tsx` rendered
`k={diagnostics?.rrf_k ?? 60}` — a hardcoded fallback that decides what a
participant reads, on a line that also mislabelled unweighted RRF as "Weighted
RRF". Both fixed.

---

## LOSS-4 — the MATERIALIZED question (closed, not a defect)

**The question.** `search_hybrid_rrf` assembles three arm CTEs and fuses them.
If the planner were free to inline those CTEs and push the fusion's `LIMIT` down
into them, the per-arm candidate caps would not hold, and the ranks entering RRF
would not match the ranks each arm produces in isolation. That would make the
diagnostics the workshop displays a fiction.

**Verdict: not a defect. No `MATERIALIZED` hint is required.**

**Why.** The three arms are not inline CTEs; each is a `LANGUAGE sql` function
(`mosaic_search.search_fts`, `search_trigram`, `search_vector`). A SQL function
invoked in `FROM` is an optimization fence for this purpose: its own
`ORDER BY ... LIMIT` is evaluated to completion, so the per-arm cap holds in the
chosen plan and the ranks entering fusion are the arms' own ranks.

Structural half re-verified 2026-08-10 against the live cluster:

```
function               lang   volatile parallel
search_fts             sql    s        s
search_hybrid_rrf      sql    s        s
search_trigram         sql    s        s
search_vector          sql    s        s
```

**Earlier measurement, recorded for provenance.** Against the snapshot-restored
500K database: ranks entering RRF matched isolated arm ranks on 24 of 24
compared rows, and the latency delta with and without `MATERIALIZED` was about
11 ms — noise at this scale.

**Method, to rerun.** `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` the fusion function
with and without `MATERIALIZED` on the arm CTEs at 500K rows, and compare both
the per-arm row counts and the ranks reaching the fusion step against each arm
called in isolation.

**Side finding, tracked separately.** `mosaic_search.search_trigram` takes
roughly 1.34 s at 500K rows. That is a performance item in its own right, not a
correctness one, and it is not Phase 2 scope.

**Inheritance.** Phase 2 Unit D's weighted fusion function is also a
`LANGUAGE sql` function over the same three arm functions, so it inherits the
same fence semantics and needs no hint either. Unit D's diagnostics endpoint
asserts that both fusion functions receive an identical candidate list — same
arm caps, same per-arm ranks — and differ only in fusion arithmetic, which
re-proves the substrate on every call rather than trusting this record.

**What would have caught it.** An assertion that arm ranks reaching fusion equal
arm ranks in isolation. Unit D's endpoint becomes that assertion.

---

## SUBSTRATE-1 — the `catalog.*` databases are gone; equivalence is impossible

Recorded 2026-08-10 as Unit E's pre-flight receipt. Not a loss of capability: a
loss of the **ability to verify** one.

**Verified.** `catalog_workshop` and `catalog_codex_20260807` do not exist. The
local server lists `coffee`, `postgres`, `template0`, `template1` and nothing
else. Live Aurora has `mosaic`, `mosaic_bench`, `mosaic_eval`, `mosaic_search`,
`mosaic_stage`, `public` — no `catalog` schema. No dump, no archive, and no
committed golden output exists anywhere in the tree; the one committed benchmark
artifact (`data/benchmarks/scale_projection.csv`) is output from
`simulate_scale.py`, which never touched `catalog.*`.

The DDL survives in `sql/` — `01_schema.sql` still declares
`CREATE SCHEMA IF NOT EXISTS catalog`. The **loaded state** does not: 500,000 rows
with real Cohere embeddings, unreconstructible without re-embedding, and the
existing embedding cache is keyed to the `mosaic_*` projection.

**Consequence.** "Diff the ported script against its predecessor" is unavailable
for every consumer — not because the code is missing but because the data it read
is. Unit E's definition of done is therefore a recorded **correctness** statement
against live `mosaic_*`, with the no-baseline risk named per script, replacing
equivalence. Rebuilding a `catalog.*` baseline was considered and rejected: it
would resurrect a deliberately deprecated tree onto the live cluster, and at any
reduced scale the latency numbers would not transfer, so it buys a baseline that
is not the real baseline.

### `sql/` inventory — 11 files, reconciled

The earlier count of 10 predates `08_benchmark_schema.sql` being noticed. Git
confirms 11 tracked files.

| File | Defines | Superseded by |
|---|---|---|
| `00_extensions.sql` | extensions | `db/sql/00_extensions.sql` |
| `01_schema.sql` | `catalog`, `catalog_stage`, `catalog_eval` + tables | `db/sql/01`–`06` |
| `02_load_catalog.sql` | catalog COPY path | `db/sql/17_load_normalized_catalog.sql` |
| `02_load_media.sql` | media COPY path | `db/sql/04_media.sql`, `15_load_premium_cohort.sql` |
| `02_upsert_from_stage.sql` | stage → live upsert | `db/sql/17` |
| `03_indexes.sql` | catalog indexes | `db/sql/07_indexes.sql`, `08_indexes_concurrent.sql` |
| `04_search_functions.sql` | `catalog.search_lexical/trigram/vector/hybrid_rrf` | `db/sql/09_search_functions.sql` |
| `05_typo_tolerance_lab.sql` | trigram lab | `db/sql/lab_01_typo_tolerance.sql` |
| `06_hnsw_performance_lab.sql` | HNSW lab + `product_ce_embedding_hnsw_idx` | `db/sql/08_indexes_concurrent.sql` + advanced lane |
| `07_load_reviews_and_evals.sql` | reviews, eval seed | `db/sql/11_evaluation.sql` |
| `08_benchmark_schema.sql` | `catalog_bench`, `catalog_bench.vector_item` | `db/sql/13_benchmark.sql` |

### Consumer disposition — case per consumer

Case assignments follow the verdict above rather than preceding it. Case 1
(predecessor runs, diff recorded) is **unavailable for all six**.

| Consumer | Touches | Case | Correctness bar |
|---|---|---|---|
| `scripts/run_eval.py` | `catalog.search_hybrid_rrf`; reads `queries.jsonl` | **3** — runs, output untrustworthy | the golden missions' expected targets. The contract gate's `A2` checks are the baseline that *does* exist, so correctness is stated against them, not against the old output |
| `scripts/benchmark_hnsw.py` | `catalog.product` | **3** — A-MINIMAL | ported to run against `mosaic_*`, connectivity proven. **Output contract deferred to Phase 3's advanced-lane spec** (`bench.runs` shape, ground-truth recall definition), so Phase 3 finds it waiting rather than broken |
| `scripts/load_catalog.py` | `catalog.product`, `catalog_stage.product_raw` | **2** | superseded-by pointer to `db/sql/17_load_normalized_catalog.sql` + `make db-load-mosaic`, then deleted |
| `scripts/load_media.py` | `catalog.product_media`, `catalog_stage.product_media_raw` | **2** | superseded-by pointer to `db/sql/04_media.sql` + `15_load_premium_cohort.sql`, then deleted |
| `tests/test_sql_integration.py` | 4 `catalog.*` functions | **2** | already skips (no `TEST_DATABASE_URL`); retarget to `mosaic_search` or delete, reason stated |
| `ui/src/showcase.test.ts` | `catalog.facets`, `catalog.products` in a string | **2** | stale string, not a live call; delete the reference |

**Also in Unit E's scope, found during this pre-flight.** Five Makefile targets
still install or read the dead tree and would apply it to whatever DSN they are
handed: `db-init` (runs `sql/00` + `sql/01`), `db-load`, `db-load-catalog`,
`db-load-media`, `db-index` (runs `sql/03`). Plus `config/.env.example` and two
`README.md` examples still show a `localhost` DSN, which the Aurora-only policy
in `ARTIFACTS.md` forbids.

**What would have caught it.** Nothing tracked which databases held
irreplaceable state. `ARTIFACTS.md` now does, and records that the snapshot is
the only restore path.

---

## BEHAVIOR-1 — `BUSINESS_WEIGHT=` empty now falls through to the yaml

Recorded 2026-08-10, Phase 2 Units C and D. A deliberate behavior change, entered
here because it reverses an assertion an existing test made and a reader would
otherwise find the two irreconcilable.

**Before.** `service/config.py` read `os.getenv("BUSINESS_WEIGHT", "0.003")` and
passed the result to `float()`. An empty variable — `BUSINESS_WEIGHT=` in a `.env`
— reached `float("")`, raised, and the process refused to start.
`tests/test_service_config.py` asserted exactly that for `["-0.1", "abc", ""]`.

**After.** The value comes from `db/config/retrieval.yaml`, and an empty
environment variable is treated as **the absence of an override**, so the
validated yaml value is used.

**Why the change is right.** With a string literal in the module there was nothing
to fall back *to*, so refusing was the only honest option. Now there is a
validated single source. An empty variable is not a value a user chose; it is
usually a generated `.env` with an uninterpolated line, and taking the whole API
down over a setting the yaml already answers is a worse failure than proceeding
with the declared default.

**What is preserved.** The property Phase 1 bought remains: an
**out-of-range** value still refuses to start. `BUSINESS_WEIGHT=0.15` — the exact
value behind the Phase 1 crash, where `config/.env.example` shipped it against a
`le=0.05` bound and every search returned an unhandled HTTP 500 — is still a
startup failure, as is any non-numeric string. Empty can no longer produce an
unvalidated config, because there is no code path where it yields anything but the
bounds-checked yaml value.

| Value | Before | After |
|---|---|---|
| unset | 0.003 (literal) | 0.003 (yaml) |
| `` (empty) | **refuses to start** | 0.003 (yaml) |
| `0.15` | refuses to start | refuses to start |
| `-0.1` | refuses to start | refuses to start |
| `abc` | refuses to start | refuses to start |

**What would have caught a mistake here.** The fixture, which is permanent:
`test_an_empty_override_falls_through_to_the_yaml` alongside the parametrised
refusals in `tests/test_service_config.py`, and `test_an_empty_environment_variable_does_not_win`
in `tests/test_retrieval_profile.py`. The change is asserted in both directions
rather than described.

---

## LOSS-5 — an arm claimed on a mission it does not serve (closed)

Recorded 2026-08-10, Phase 2 Unit B. Not a rewrite loss: a claim that was never
true and that no gate could contradict until `declares ⇒ asserts` existed.

**The claim.** `typo-recovery` listed `hnsw` in `expected_techniques`. The
workshop's headline mission for misspelled input asserted, by declaration, that
the semantic arm contributes to recovering it.

**Measured on the live cluster.** Query
`wirless noice canceling hedphones under $200 with long batery life`, every token
misspelled, each arm run alone under the mission's own filters:

| Arm | Pool | Target 2 rank |
|---|---:|---:|
| `fts` | 120 | **1** |
| `pg_trgm` | 80 | **1** |
| `hnsw` | 150 | **not recalled** |

The vector arm returns a full 150-row pool and does not contain the mission's
target. Cohere Embed v4 on an all-misspelled string produces a vector whose
neighbours are plausible headphones — just not this one.

**Resolution: `hnsw` un-declared**, rather than asserted. This is the case that
justifies the falsifier requirement. `semantic_signal_present` would have *passed*
here, on a pool size of 150, while the arm contributed nothing to the outcome —
an assertion that cannot fail on the mission it is attached to. Adding it for
symmetry with the other four violations would have been the exact defect shape
Phase 1 was created to remove, reintroduced by a rule meant to prevent it.

**What would have caught it.** Nothing did, for the mission's whole life: pool
counts were never compared against target recall per arm. `declares ⇒ asserts`
surfaced the declaration; only measuring the arm alone decided whether to assert
it or drop it. The lesson the mission actually teaches — that fuzzy matching
recovers what embeddings do not — is now stated by the contract rather than
contradicted by it.
