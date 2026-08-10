# Artifacts and infrastructure

Where the live state lives, what can be restored, and what cannot.

## Infrastructure policy: Aurora only

**No local databases exist or will exist.**

- The **Aurora PostgreSQL cluster** in `us-east-1` holds the only live tree
  (`mosaic`, `mosaic_search`, `mosaic_stage`, `mosaic_eval`, `mosaic_bench`),
  500,000 products with real Cohere Embed v4 vectors at 1024 dimensions.
- The **cluster snapshot** is the only restore path. There is no local rebuild.
- Every `make` bootstrap target points at Aurora via `DATABASE_URL`.
- Any Makefile target, script, or document that assumes a local PostgreSQL is
  updated or deleted. This is not advisory: several targets currently install a
  deleted schema onto whatever DSN they are handed. See "Known hazards" below.

Rationale is recorded in `docs/house-standards.md` §6. In short: the loaded state
of the pre-rewrite `catalog.*` tree existed only in two local databases, they
were dropped, and 500,000 rows of real embeddings cannot be reconstructed without
re-embedding. Local state that nothing can restore is not a convenience.

## What is restorable

| Artifact | Location | Restore path |
|---|---|---|
| Catalog + embeddings | Aurora `mosaic_*` | cluster snapshot |
| Embedding cache | `build/embedding-cache/` | `make db-import-embeddings` (keyed to `mosaic_*`) |
| Normalized CSV shards | `build/normalized/` | `make db-prepare-mosaic` from `data/full/*.csv.gz` |
| Premium cohort media | `ui/public/assets/images/mosaic/` | git; 126 files, content-verified |
| Mission contract | `data/evals/mosaic_labs_missions.json` | git; validated by `make validate-missions` |
| Retrieval numbers | `db/config/retrieval.yaml` | git; single source, enforced by `scripts/config_tripwire.py` |

## What is not restorable

**The `catalog.*` tree's loaded state.** Two local databases —
`catalog_workshop` and `catalog_codex_20260807` — held the only populated copy.
Both were dropped in August 2026. Verified 2026-08-10: neither exists, and the
live Aurora cluster has no `catalog` schema.

The DDL survives in `sql/` (11 files, all carrying deprecation headers). The data
does not. Consequence: no ported script can be diffed against its predecessor,
which is why Unit E's definition of done is a recorded **correctness** statement
against live `mosaic_*` rather than an equivalence diff. See
`docs/rewrite-losses.md`.

## Known hazards

- `make db-init`, `db-load`, `db-load-catalog`, `db-load-media`, `db-index` still
  target the dead `catalog.*` tree and would install it onto any DSN given to
  them. In scope for Unit E: retarget to the `mosaic_*` equivalents or delete.
- `config/.env.example` and two `README.md` examples still show a `localhost`
  DSN. Same scope.
- `scripts/run_eval.py` reads `data/evals/queries.jsonl` against
  `catalog.search_hybrid_rrf`, which does not exist. It runs and produces
  nothing trustworthy.
