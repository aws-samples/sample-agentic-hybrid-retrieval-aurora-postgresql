# Rewrite loss register

Append-only. Capabilities that existed in the `catalog.*` tree and did not
survive the rewrite to `mosaic_*`, plus one measurement question that the
rewrite raised and closed.

This file exists because three decisions lived in conversation rather than in
files, and a later session could not cite them. Every entry states the
substance, the evidence, and **what would have caught it** — because in every
case the answer is an assertion or a gate that did not exist.

Entries are never edited to hide a mistake. Corrections are appended to the
entry with a date.

All measurements below were taken against the live 500,000-product Aurora
PostgreSQL 18.3 cluster (`mosaic_catalog`), read-only unless stated.

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
