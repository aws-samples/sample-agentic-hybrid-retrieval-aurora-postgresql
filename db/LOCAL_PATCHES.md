# Local patches to the vendored data-model package

`db/` is a vendored copy of `mosaic-data-models-aurora-v1`, rendered at
**vector(1024)**. These are the changes made here that must go back upstream, so
a future re-vendor does not silently reintroduce them.

The package's own validation is static — it checks JSON Schemas, cohort counts,
SQL file ordering, and Pydantic loading, but it never executes the SQL against a
PostgreSQL server. Both defects below were found by installing into a scratch
database (PostgreSQL 18.4, pgvector 0.8.5) and exercising the retrieval arms with
real rows.

---

## 1. `install.sql` aborted: jsonb operator precedence

**File:** `sql/09_search_functions.sql`, `mosaic_search.matches_filters`

```sql
-- was: fails to parse
(NOT (f ? 'attributes') OR (d).attributes @> f->'attributes')
-- now
(NOT (f ? 'attributes') OR (d).attributes @> (f->'attributes'))
```

`@>` and `->` share a precedence level and associate left, so the original
parsed as `((d).attributes @> f) -> 'attributes'` and raised:

```text
ERROR:  operator does not exist: boolean -> unknown
```

This aborted `install.sql` at file 09 of 20, so **the schema could not be
installed at all**. Severity: blocking.

## 2. The typo-recovery arm could not recover typos

**File:** `sql/09_search_functions.sql`, `mosaic_search.search_trigram`

```sql
-- was: whole-string gate only
AND d.trigram_text % lower(q)
-- now
AND (d.trigram_text % lower(q) OR lower(q) <% d.trigram_text)
```

plus an added GUC, because `<%` reads a different threshold:

```sql
SET pg_trgm.word_similarity_threshold = 0.5
```

The function already *scored* with `greatest(similarity, word_similarity,
strict_word_similarity)`, which is right. But the `WHERE` gate used `%` alone,
and `%` compares whole strings. `trigram_text` is a long concatenated document,
so a short misspelling dilutes below the threshold and the row is discarded
before the correct score is ever computed.

Measured against a 90-character `trigram_text`:

| Query | `similarity` (gate) | `word_similarity` (score) | Old result | New result |
|---|---:|---:|---|---|
| `auralux` | 0.11 | 0.88 | 0 rows | product 1 @ 0.875 |
| `sonora c72` | — | 0.91 | 0 rows | product 2 @ 0.909 |
| `headfones` | — | 0.50 | 0 rows | both @ 0.500 |
| `zzzqqqxyw` | — | — | 0 rows | 0 rows (correct) |

Severity: high. The pg_trgm arm is one of the three the workshop teaches; it
returned nothing for every realistic misspelling, so RRF fusion silently
degraded to two arms.

**Still indexable.** `<%` is supported by the same `gin_trgm_ops` index, and the
planner uses both branches:

```text
Bitmap Heap Scan on product_document
  ->  BitmapOr
        ->  Bitmap Index Scan on product_document_trigram_gin_idx
              Index Cond: (trigram_text % 'auralux'::text)
        ->  Bitmap Index Scan on product_document_trigram_gin_idx
              Index Cond: (trigram_text %> 'auralux'::text)
```

---

## 3. Three tables removed; install split into core and labs

The package installs 30 base tables. The application reads 11. For a 60-minute
L400 session that is 19 empty tables a participant has to look past, so the
install is now two files and three tables are gone.

**Removed outright** — each duplicated something already recorded, and two
places holding one fact is how they come to disagree:

| Table | Why |
|---|---|
| `mosaic.rerank_event` | `search_event` already carries the query, profile, and timings |
| `mosaic.rerank_result` | `search_result_event.rerank_rank` and its `scores` jsonb already hold the reranked order and score |
| `mosaic.interaction_event` | Click/impression telemetry with no producer anywhere in the application |

Also dropped: their four indexes, the `rerank_event` → `search_event` foreign key
in `12_telemetry.sql`, and `10_agent_and_rerank.sql` is renamed
`10_agent_audit.sql` since it no longer models reranking.

**Split, not deleted.** `mosaic_eval.*` (5 tables) and `mosaic_bench.*` (4) move
to `install_labs.sql`. They are how Recall@10, latency, and HNSW build time get
measured, so removing them would mean rebuilding them later — but they start
empty and nobody needs them open during the session.

```bash
make db-install       # 18 tables: everything the application reads
make db-install-labs  # +9: mosaic_eval and mosaic_bench
```

Verified: core install 18 tables, with labs 27. Retrieval, fusion, provenance,
and the smoke test are unchanged after the cuts.

**What stays, and why nothing was merged.** Folding `product_offer` back into
`product` would collapse the distinction the session exists to teach — that
`embedding_text` excludes volatile price while `rerank_text` includes it. The
two-table split is the lesson, not overhead. Five tables carry the teaching:

1. `mosaic_search.product_document` — the five retrieval representations
2. `mosaic.search_result_event` — which arm found this, at which rank
3. `mosaic.search_event` — profile, counts, timings for one query
4. `mosaic.product_evidence` — why evidence gets its own vector
5. `mosaic.product` + `product_offer` — durable content vs volatile commerce state

## 4. Configuration said 768 while the SQL says 1024

`config/retrieval.yaml` (`dimensions`) and `config/model.env.example`
(`EMBEDDING_DIM`) both stated 768 after rendering to 1024. Corrected here.
Re-rendering with `make db-render VECTOR_DIM=…` rewrites the SQL but not these
two files, so they need updating by hand or the renderer needs extending.

---

## Verified working after patching

Installed clean, then exercised with two real products:

- 5 schemas, 35 tables, 9 functions
- 3 vector columns, all `vector(1024)`
- FTS, trigram, and vector arms each return ranked rows
- `search_hybrid_rrf` fuses them with per-channel provenance
- Filters: `max_price_cents`, `in_stock_only`, and jsonb `attributes` containment
- The teaching invariant holds: `embedding_text` excludes current price,
  `rerank_text` includes it

Not yet measured, and not to be quoted until it is: HNSW build time, execution
plans at scale, latency, QPS, Recall@10. Those require the real Aurora cluster.
