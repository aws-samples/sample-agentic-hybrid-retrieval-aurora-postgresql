# Hybrid Retrieval Workbench session handoff

This package is design history for the DAT410 builders session. The live
repository root, `AGENTS.md`, `HANDOFF.md`, and
`docs/builder-session-flow.md` govern implementation work.

## Document precedence

1. `docs/SPEC-session.md` defines the current 60-minute session contract.
2. `../../docs/architecture.md`, `../../docs/data-model.md`, and the live code
   define implemented ownership and behavior.
3. `docs/verity-implementation-spec.md` and
   `docs/verity-ui-design-system.md` retain design rationale.
4. `reference/concept-screens/` contains non-shipping visual references.

Do not revive requirements from an older draft when they disagree with the
current spec or live application.

## Current spine

The required path is:

1. reproduce the lock mechanism with the nine scripts in `labs/incident/`;
2. build exact, full-text, semantic, fuzzy, filtered, and fused retrieval;
3. run the incident agent and synthesize a cited answer; and
4. inspect diagnostics and replay persisted proof.

The controlled incident uses 25,000 rows in `workbench_lab.orders`. Its open
transaction preserves a genuine PostgreSQL `ShareLock` long enough to inspect.
That proves lock compatibility and the wait chain; it is not a production
duration or throughput benchmark.

The former 25-million-row `shop.orders`, pgbench services, 3 GB working-set
claim, and 240-420 second calibration gate are deferred production-scale ideas.
There are no shipped assets for them. Do not implement or cite them as current
workshop behavior.

RLS with `pg_columnmask`, AgentCore Gateway, evidence admission, connector
operations, and extensive HNSW tuning are optional modules. None may block the
core workshop.

## Non-negotiable implementation rules

- Keep canonical retrieval and fusion in `retrieval.*` SQL.
- Keep raw arm scores, RRF, and rerank scores separate.
- Persist candidate signals before synthesis.
- Never fabricate evidence, telemetry, citations, or derived values.
- Generate adapters from `agent/registry.py`; do not hand-edit generated files.
- Keep `design/SPEC-session.md` and this package's `docs/SPEC-session.md`
  byte-identical.
- Build the Workshop Studio archive only from committed source and a matching
  v2 dump produced from a disposable database.

## Validation

Run the relevant application tests, the static release gates, `git diff
--check`, and the exact incident scripts on target Aurora before publication.
Workshop Studio pushes and publication remain event-owner managed.
