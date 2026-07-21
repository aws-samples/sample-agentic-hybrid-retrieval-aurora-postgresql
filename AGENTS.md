# Agent Guidance

## Mission

Extend Verity as an evidence system, not as a generic chatbot. Aurora
PostgreSQL owns cross-source retrieval, ranking, joins, citations, evaluation,
and replayable proof. Operational systems remain authoritative for workflow,
permissions, mutable state, and actions.

## Start Here

Read only the material relevant to the task:

- `README.md`: product boundary, local runbook, and repository layout.
- `docs/architecture.md`: service and ownership boundaries.
- `docs/data-model.md`: canonical `ops.*` tables.
- `docs/ingestion-api.md`: normalized source-object contract.
- `docs/connector-lifecycle.md`: cursor, update, tombstone, and index lifecycle.
- `docs/live-index-lab.md`: controlled repository-update proof.

For connector, retrieval, ranking, citation, or evaluation work, apply
`.claude/skills/extend-hybrid-retrieval/SKILL.md`.

## Repository Map

| Path | Owns |
|---|---|
| `backend/app/` | FastAPI endpoints, ingestion, embeddings, retrieval, rerank, agent tools, and synthesis |
| `sql/` | Schema, indexes, canonical search functions, diagnostics, and evaluation |
| `connectors/` | Source transports and normalization into `SourceObject` |
| `frontend/` | Inspection UI over API responses and persisted proof |
| `lambda_mcp/` | Stateless AgentCore Gateway adapter over the API |
| `mcp-server/` | Optional MCP wrapper over the same API |
| `seed/` | Deterministic Orion corpus and restore artifact |
| `scripts/` | Environment and managed-boundary helpers |
| `docs/` | Architecture, participant flow, and production guidance |

This repository is application source only. Workshop infrastructure and the
packaged source archive belong in the sibling Workshop Studio repository.

## Invariants

- Choose explicitly whether evidence is materialized, federated, or revalidated
  live. Do not copy a source merely because a connector is possible.
- Keep ranking in the canonical `ops.*_search` SQL functions. Agent tools,
  Gateway adapters, and the frontend consume the API; they do not reimplement
  fusion.
- Preserve stable source identity, URL, revision or cursor, content hash, ACL,
  and citation metadata.
- Use `upsert` for deltas and `full` for snapshot reconciliation. Tombstone
  missing source objects; do not hard-delete rows referenced by historical runs.
- Re-embed only changed chunks. Use the same embedding space for stored
  documents and live queries.
- Apply filters and ACLs before every retrieval arm enters fusion.
- Persist the retrieval run and candidate-level signals before synthesis.
- Never fabricate source IDs, titles, scores, citations, or canonical data when
  the database or an external source is unavailable.
- Do not add a PostgreSQL extension unless it is supported by the target Aurora
  PostgreSQL engine version and required by the workshop contract.

## Working Loop

1. Inspect the relevant contract and current implementation.
2. Run `make doctor` before database-dependent work.
3. Make the smallest change at the owning boundary.
4. Validate exact-symbol, semantic, fuzzy, filter, ACL, citation, and receipt
   behavior as applicable.
5. Run `git diff --check` and report any validation that could not run.

Do not commit credentials, generated live exports, local databases, logs,
`node_modules`, or `.claude/settings.local.json`.
