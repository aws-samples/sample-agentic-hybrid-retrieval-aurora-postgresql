# Workshop seed — the canonical Orion corpus

This directory generates a **byte-identical** dataset for the hybrid-retrieval
demo and restores it into Aurora (or local Postgres). The demo answers one
canonical question — **"Why did Orion slip?"** — and every number the five
Threadline views show (the answer, the six citations, the trail, the diagnostics
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

Embeddings are computed **offline** — no Bedrock calls during provisioning. The
default `hash` provider is deterministic and workshop-safe; pass
`--provider bedrock` to use Cohere `embed-v4` (1024-d) when credentials are
present and you want production-fidelity vectors.

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

Provisioning is **$0 in Bedrock spend** with the default `hash` embeddings — the
dump ships precomputed 1024-d vectors, so restoring it makes no model calls. The
`bedrock` provider is only exercised if a seed author explicitly regenerates with
`--provider bedrock` (Cohere `embed-v4`, ~150 `search_document` embeddings). At
query time the demo also makes no Bedrock calls unless the backend is configured
with `EMBED_PROVIDER=bedrock`.

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
  `titan-embed-v2`. The schema, indexes, and dump are all 1024-d.
- **Session number:** any `DAT409`-style session references are placeholders and
  will change.
