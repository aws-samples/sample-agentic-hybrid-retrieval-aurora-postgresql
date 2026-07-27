# Codex task checklist

## Phase 0 — baseline

- inspect existing repository;
- identify current ID constants and snapshots;
- run tests/build before changes;
- create a migration branch.

## Phase 1 — identifier migration

- apply `fixtures/id-migration.json`;
- update SQL seeds and relationships;
- update test expectations;
- update API fixtures;
- update UI fixtures;
- update docs;
- verify no old canonical IDs remain outside `reference/`.

## Phase 2 — contract stabilization

- add `contract_version`;
- align Pydantic/TypeScript schemas with OpenAPI;
- add `proof.transport_invocations`;
- add `POST /v1/tools/explain-ranking` if absent;
- ensure adapters call shared services.

## Phase 3 — Module 1 UI

- implement `/retrieve`;
- exact/FTS, semantic, fuzzy, fused;
- presets;
- principal;
- rerank;
- candidate receipt drawer;
- RRF controls.

## Phase 4 — Module 2 UI

- implement `/prove`;
- answer/graph/plan/receipt tabs;
- Database Insights actions;
- evaluation summary;
- plan type honesty.

## Phase 5 — Module 3 adapters

- local stdio MCP;
- package OpenAPI;
- document AgentCore target;
- captured output format;
- parity normalizer/test.

## Phase 6 — Module 3 UI

- implement `/tools`;
- transport cards;
- tool selector;
- sample request;
- normalized result;
- parity matrix.

## Phase 7 — QA

- backend tests;
- frontend build;
- responsive;
- accessibility;
- no remote fonts;
- no vendor logos;
- no old IDs;
- parity test;
- release receipts.
