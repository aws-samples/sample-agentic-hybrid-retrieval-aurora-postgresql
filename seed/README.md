# Workshop seed — the canonical Orion corpus

This directory generates a **byte-identical** dataset for the hybrid-retrieval
demo and restores it into Aurora (or local Postgres). The demo answers one
canonical question — **"Why did Orion slip?"** — and every number the five
AuraLens views show (the answer, the six citations, the trail, the diagnostics
funnel) is backed by real rows in the `ops` schema, not hardcoded in the UI.

## What gets built

| Artifact | What it is |
| --- | --- |
| `artifacts/source_objects.jsonl` | All **150** source objects (deterministic; 30 per system). |
| `artifacts/manifest.json` | Corpus summary — counts, cited order, embedding model/dim, run slug. |
| `artifacts/hybrid-retrieval-seed-v1.dump` | `pg_dump -Fc` archive of the fully populated `ops` schema. |

The dump carries: `source_objects` (150) · `object_chunks` with **1024-d
embeddings** · `citations` · `object_links` (the golden-thread edges) ·
`retrieval_runs` + `retrieval_candidates` (the canonical run `rr_7f3a9c`) ·
`agent_answers` (the exact Orion answer + plan) · `retrieval_run_metrics` (the
diagnostics funnel + stage timings) · `evaluation_queries` +
`relevance_judgments`.

## The two workflows

### Regenerate (seed authors only)

Rebuilds the dataset and the dump from source. Needs a reachable Postgres 18 +
pgvector ≥ 0.8.1 via `DATABASE_URL`.

```bash
# JSONL + manifest only — no database needed, fast sanity check:
python seed/generate.py --jsonl-only

# Full rebuild — populate the DB and write the -Fc dump:
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable \
  python seed/generate.py
```

Embeddings are computed **offline at build time** — no Bedrock calls during
*provisioning* (the dump ships precomputed vectors). The committed
`hybrid-retrieval-seed-v1.dump` carries **real Cohere `embed-v4` (1024-d)**
vectors (`--provider bedrock`, the default when regenerating for the workshop).
For a fully offline, $0 local rebuild, pass `--provider hash` — deterministic and
credential-free, but see the runtime note below.

> **Runtime provider must match the dump.** The stored chunk vectors and the
> query vector must live in the *same* embedding space. If the loaded dump has
> Cohere vectors, the backend must run with `EMBED_PROVIDER=bedrock` so live
> `/v1/search` embeds queries with Cohere too; a `hash`-provider query against
> Cohere documents returns meaningless neighbors. The canonical Orion demo answer
> is unaffected either way — it is served from the stored `ops.agent_answers` row,
> not recomputed at query time.

### Load / restore (workshop attendees, Workshop Studio bootstrap)

Restores the prebuilt dump — idempotent, safe to re-run.

```bash
DATABASE_URL=postgresql://<aurora-endpoint>/retrieval \
  seed/load.sh
```

`load.sh` (1) ensures extensions + schema, (2) `pg_restore`s the `-Fc` artifact
with `--clean --if-exists`, (3) **rebuilds indexes after the data load** — the
HNSW graph (`m=16, ef_construction=64, vector_cosine_ops`) is built once over the
full vector set, plus the GIN full-text and `pg_trgm` fuzzy indexes — and (4)
runs `ANALYZE`.

## Cost note

Provisioning is **$0 in Bedrock spend** regardless of provider — the dump ships
precomputed 1024-d vectors, so `pg_restore` makes no model calls. Embedding spend
happens only **once, at build time**, when a seed author regenerates the dump:
`--provider bedrock` makes ~150 `search_document` Cohere `embed-v4` calls (a few
cents total); `--provider hash` makes none. Every workshop attendee then reuses
that one prebuilt artifact — the embeddings are generated exactly once and
restored verbatim thereafter.

At query time the demo's canonical answer makes no Bedrock calls (it is served
from `ops.agent_answers`). Ad-hoc `/v1/search` queries embed the query text with
whatever `EMBED_PROVIDER` the backend is set to — set it to `bedrock` to match a
Cohere dump (see the runtime note above).

## Divergences from the original five HTML mockups (flagged)

These are intentional and were directed during the build. The seed and UI are
internally consistent with each other; they differ from the *original static
mockups* as follows:

- **Systems:** ServiceNow is dropped. The five connected systems are **Slack,
  Jira, Confluence, Salesforce, GitHub**.
- **Citation [5]:** the former ServiceNow `INC-0012345` is now a **Jira ops
  ticket `ORION-1489`** ("replication_lag_seconds > 60 paging in prod"), surfaced
  primarily by **full-text search** — a teaching example of the lexical ranker.
  Two of the six citations are now Jira (the blocker `ORION-1473` + this ops
  ticket). The answer meta stays **6 sources · 5 systems**.
- **Corpus size:** **150 objects, symmetric 30 per system** (the mockups implied
  "All 148"). The candidate funnel is `150 → 6`.
- **Embedding model:** the run metadata reads **`cohere.embed-v4 · 1024d`** (per
  the workshop's Bedrock model set), where an early mockup draft said
  `titan-embed-v2`. The schema, indexes, and dump are all 1024-d, and the shipped
  dump carries **real Cohere `embed-v4` vectors** (not the offline `hash`
  fallback).
- **Session number:** any `DAT409`-style session references are placeholders and
  will change.
