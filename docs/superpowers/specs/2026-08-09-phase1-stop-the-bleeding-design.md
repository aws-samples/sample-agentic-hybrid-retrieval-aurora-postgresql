# Phase 1 — Stop the bleeding

Fixes for defects that fail in front of participants. Scope is exactly 1.1–1.4.
Every item states its verification before implementation.

Baseline `d29496c`. All measurements below were taken on PostgreSQL 17.10 with
pgvector 0.8.5 and pg_trgm 1.6, against product text reconstructed from the real
catalog shards exactly as `db/sql/06_retrieval_projection.sql` builds
`search_document`.

## Precondition

`docs/intentional-gaps.md` records that this repository ships nothing
deliberately broken, so no fix in this phase can collide with a planted
exercise. Both repair-checkpoint capabilities were verified live at `d29496c`.

## 1.1 Business-weight bound

**Defect.** `config/.env.example:13` ships `BUSINESS_WEIGHT=0.15`.
`service/models.py:165` bounds `business_weight` at `le=0.05`. Copying the
example env file makes every search fail.

**Why it reaches a request.** `service/config.py:92` reads the value with no
range check, so `get_settings()` accepts it:

```
BUSINESS_WEIGHT=0.15 → get_settings() ACCEPTED business_weight = 0.15
```

The bound is only enforced when `RetrievalProfile` is constructed per request,
raising `ValidationError`. `/api/search` catches `ClientError`, `BotoCoreError`
and `RuntimeError`, so a pydantic error escapes as an unhandled HTTP 500 on
every query.

**Fix.**

1. `config/.env.example` → `BUSINESS_WEIGHT=0.003`, matching
   `db/config/retrieval.yaml:15`, the value the engine already uses.
2. Add range validation to `Settings` construction. An out-of-range weight
   raises `ConfigurationError` naming the parameter, the offending value, and
   the violated bound. A config that cannot serve a request must not yield a
   running process.

Bounds are declared once, next to the setting, and are the same numbers
`RetrievalProfile` enforces. Phase 2 makes `retrieval.yaml` their single source;
this phase only stops the crash.

**Verification.**

- `BUSINESS_WEIGHT=0.15` → process exits before serving, message contains
  `business_weight`, `0.15`, and `0.05`.
- `BUSINESS_WEIGHT=0.003` → import succeeds, `RetrievalProfile` validates.
- Negative and non-numeric values are rejected the same way.

## 1.2 FTS arm returns nothing

**Root cause: the query builder.** Not tokenization, not the index, not an
intentional gap.

`mosaic_search.search_fts` (`db/sql/09_search_functions.sql:76`) builds only
`websearch_to_tsquery`, which ANDs every term. A conversational query requires
every token to be present in one document; misspelled tokens exist in no
document, so the conjunction is unsatisfiable and the arm returns zero rows.
`trigram_text`, the GIN indexes, and the weighted `search_document` are all
correct.

The sibling `catalog.*` tree already carries the fix
(`sql/04_search_functions.sql:36` OR-combines the lexemes). It was lost in the
rewrite to `mosaic_*`.

**Measured, against 6,006 real products including every mission target and its
same-subcategory competitors.** `shipped_rank`/`fixed_rank` are the target's
position in the FTS arm.

| Mission | declares `fts` | shipped | fixed |
|---|---|---:|---:|
| `exact-identity` | yes | 1 | 1 |
| `typo-recovery` | yes | — | 1 |
| `semantic-eligibility` | yes | — | 1 |
| `rank-with-evidence` | no | — | 1 |
| `agentic-research` | no | — | 1 |
| `hnsw-performance` | no | 1 | 1 |

Three missions lose the arm entirely under the shipped builder. Two of them
(`typo-recovery`, `semantic-eligibility`) declare `fts` in
`expected_techniques`, so those are contract violations. The others do not
declare it, so their recovery is a side effect, not a requirement — and Phase 4
must keep arm assertions mission-scoped so a principled abstention stays a pass.

**Fix.** Combine three clauses in `search_fts`:

1. `broad_tsq` — OR-combined lexemes, for recall.
2. `strict_tsq` — `websearch_to_tsquery` unchanged, kept as a scoring bonus so
   exact identity still dominates.
3. A negation guard, below.

**Negation is load-bearing.** `tsvector_to_array` discards the `NOT` operator, so
a naive OR-combine inverts a user's exclusion:

```
websearch_to_tsquery('headphones -wireless') → 'headphon' & !'wireless'
naive OR-combine                            → 'headphon' | 'wireless'
```

The naive form admits 120 candidates the user asked to exclude. When the strict
query contains a negation, the fixed arm requires the strict match as well:

```
naive_pool 120 | safe_pool 0 | violations 0   ('headphones -wireless')
safe_pool  120 | violations 0                 ('wireless -earbuds', survivors exist)
```

`safe_pool 0` for the first is corpus truth, not over-restriction: the corpus
holds 6,001 headphone documents and 0 non-wireless ones. The control case proves
the path returns survivors when they exist and excludes correctly.

**Precision is preserved.** The strict bonus keeps exact identity decisively
first — a 2.6× score gap over the next candidate:

```
1  17001  1.8684  Mosaic EchoBud S2 Premium Wireless Earbuds
2      1  0.7222  Mosaic Auraluxe H9 Premium Wireless Headphones
3 370001  0.6875  Mosaic Forma Ergonomic Office Chair
```

**Recall cost is bounded** by `candidate_limit`; the arm widens from 0–1 rows to
4–120 out of 6,006, and RRF plus rerank order the pool.

**Edge cases, all safe.** Stopwords-only, empty, whitespace, punctuation-only
and single-character queries yield an empty tsquery that matches nothing —
warning, not exception. Quoted phrases, negations and 40× repeated terms behave.

**A new assertion is required.** No mission asserts `fts_signal_present`; the
vocabulary has no such name. The lexical arm can fail completely with every gate
green. Add `fts_signal_present` to the shared definitions module so this class
of failure is detectable. Phase 4 scopes it per mission.

**Verification.**

- The table above reproduces: two `fts`-declaring missions go `— → 1`.
- `exact-identity` stays rank 1 with the strict bonus present.
- Negation: zero results violate the exclusion; the survivor control returns a
  non-empty pool.
- All eight edge-case queries return without error.
- `fts_signal_present` fails when the arm is stubbed to return no rows.

## 1.3 MCP checkpoint 404

**Defect.** `mcp-server/catalog_mcp/server.py:137` requests
`/retrieval/runs/{run_id}`. The API serves
`/api/retrieval/events/{search_event_id}` (`service/main.py:293`). The tool
returns HTTP 404. `docs/api-contract.md:65` documents the wrong path too.

The contract tests pass (3 passed) because the fake client raises
`AssertionError` for any GET, so nothing exercises the path.

**Recommendation: fix the path, remove the checkpoint from the timed budget.**

Correcting the URL is one line and must happen — a shipped tool that 404s is
indefensible regardless of the guide. But the *checkpoint* should leave the timed
room budget:

- It needs a second process and an external MCP-compatible host inside a 4–5
  minute slot, against a 45-minute hard ceiling.
- Its failure mode is environmental (host not connected, port occupied), which
  reads to a room as "the retrieval system is broken" when it is not.
- `docs/retrieval-curriculum.md` already states it is not a separate protocol
  lab; its purpose is to prove portability, which the appendix can prove without
  consuming timed minutes.

Removing the checkpoint is not removing the capability: `make mcp-serve` and
`docs/mcp-interoperability.md` stay, and the checkpoint moves to the SELF_PACED
budget Phase 2.2 defines.

**Verification.**

- A contract test drives the real route shape and fails against
  `/retrieval/runs/`.
- `docs/api-contract.md` names `/api/retrieval/events/{search_event_id}`; grep
  finds no `/retrieval/runs/` anywhere.
- The timed budget contains no MCP checkpoint; SELF_PACED does.

## 1.4 Lab 1 teaches against a dead schema

**Defect.** `sql/05_typo_tolerance_lab.sql` is Lab 1's only artifact and queries
`catalog.product`, `catalog.search_trigram`, `catalog.product.trigram_text` —
the tree the API never reads.

**Recommendation: port, do not delete.** The file is four queries of sound
pedagogy — FTS fails, trigram recovers, `EXPLAIN` the indexed `<%` access path,
then a threshold sweep showing precision rising with the accepted score. Every
construct exists in the live tree: `mosaic_search.search_trigram`,
`mosaic_search.product_document.trigram_text`, and
`product_document_trigram_gin_idx`.

Port to `db/sql/lab_01_typo_tolerance.sql` against `mosaic_search`, and point
Lab 1 at it. Two adjustments the port must make:

1. The live `search_trigram` defaults to `0.20`, not the legacy `0.24`. Use the
   live default so the lab reflects shipped behavior.
2. The live function sets `pg_trgm.word_similarity_threshold = 0.5` at function
   scope. The lab's threshold sweep must state that it measures the scoring
   function, not the index gate, or a participant will conclude the gate moved.

The `catalog.*` original is left in place this phase; Phase 2 removes the dead
tree wholesale, and deleting it piecemeal now would strand
`tests/test_sql_integration.py`, `scripts/run_eval.py` and
`scripts/benchmark_hnsw.py`, which still target it.

**Verification.**

- The ported lab runs against a `mosaic_*` database with `ON_ERROR_STOP=1`.
- Its trigram query returns the `typo-recovery` target for
  `noice canceling hedphones`.
- The `EXPLAIN` output shows a bitmap index scan on
  `product_document_trigram_gin_idx`, proving the access path is indexed.
- Lab 1 references the ported file; no lab references `catalog.*`.

## Phase 1 exit criteria

1. All six missions execute end-to-end against a loaded `mosaic_*` database.
2. Every remaining failure appears in `docs/intentional-gaps.md` and nowhere
   else.
3. A bad `BUSINESS_WEIGHT` cannot produce a running process.
4. `fts_signal_present` exists and is exercised.
5. No lab or doc references `catalog.*`.
6. `make test`, `npm test`, `npm run build` green; no new lint findings in
   `service/`.

## Out of scope

Forked retrieval profile, forked timings, seed-dependent mission targets and
duplicated assertion lists are Phase 2. Weighted RRF is Phase 2.1. Mission
control, honesty enforcement and the advanced lane are Phase 3. Behavioral
assertions are Phase 4.
