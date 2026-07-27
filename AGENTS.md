# Agent Guidance

## Mission

Extend Verity as an incident-evidence system, not as a generic chatbot.
Aurora PostgreSQL owns retrieval, ranking, relationship reads, citations,
evaluation, and replayable proof. Operational systems remain authoritative for
workflow, current permissions, mutable state, and actions.

## Start Here

Read only the material relevant to the task:

- `README.md`: product boundary, local runbook, and repository layout.
- `docs/architecture.md`: service and ownership boundaries.
- `docs/data-model.md`: `casework`, `retrieval`, and `proof` contracts.
- `docs/ingestion-api.md`: implemented search index build contract.
- `docs/connector-lifecycle.md`: update, tombstone, readiness, and production
  connector boundaries.
- `docs/builder-session-flow.md`: strict 60-minute participant path and cut
  lines.

For search index, retrieval, ranking, citation, or evaluation work, apply
`.claude/skills/extend-hybrid-retrieval/SKILL.md`.

## Repository Map

| Path | Owns |
|---|---|
| `backend/app/` | FastAPI, search index, embeddings, retrieval, rerank, agent tools, and synthesis |
| `backend/tests/` | Unit and disposable-database contract tests |
| `sql/` | Schema, indexes, canonical search, diagnostics, receipts, and evaluation |
| `frontend/` | Inspection UI over API responses and persisted proof |
| `lambda_mcp/` | Stateless AgentCore Gateway adapter over the API |
| `mcp-server/` | Optional MCP wrapper over the same API |
| `seed/` | Deterministic synthetic database-incident corpus |
| `scripts/` | Environment and managed-boundary helpers |
| `docs/` | Architecture, participant flow, security, and production guidance |

This repository is application source only. Workshop infrastructure and the
packaged source archive belong in the sibling Workshop Studio repository.

## Invariants

- `casework.*` owns normalized relational truth in the workshop fixture.
  `retrieval.*` is one-way derived, versioned, rebuildable state.
- Do not hand-edit indexed documents or duplicate canonical relationships.
  Foreign keys are truth; `retrieval.evidence_edges` is the uniform read view.
- Keep ranking in the canonical `retrieval.*_search` SQL functions. Agent tools,
  adapters, and the frontend consume the API and do not reimplement fusion.
- Preserve stable evidence identity, source URI, revision, content hash, ACL,
  model space, and citation metadata.
- Queue each authoritative source revision. Tombstone deleted evidence and
  retain versions referenced by historical proof.
- Reuse embeddings only when both model ID and chunk hash match. Stored
  documents and live queries must use the same embedding space.
- Apply filters and ACLs before every retrieval arm enters fusion and at every
  relationship hop.
- Persist retrieval runs and candidate-level signals before synthesis.
- Keep raw arm scores, RRF, and model rerank scores separate. None is a
  probability.
- Never fabricate source IDs, titles, scores, relationships, citations, or
  canonical data when the database or model is unavailable.
- Do not add a PostgreSQL extension unless the target Aurora PostgreSQL engine
  supports it and the workshop contract requires it.
- Never present the synthetic corpus as real AWS or customer incident data.

## Working Loop

1. Inspect the owning contract and current implementation.
2. Run `make doctor` before database- or model-dependent work.
3. Make the smallest change at the owning boundary.
4. Validate exact ID, semantic, fuzzy, filter, ACL, fusion, citation, and
   receipt behavior as applicable.
5. Run `git diff --check` and report any validation that could not run.

Do not commit credentials, generated live exports, local databases, logs,
`node_modules`, or `.claude/settings.local.json`.
