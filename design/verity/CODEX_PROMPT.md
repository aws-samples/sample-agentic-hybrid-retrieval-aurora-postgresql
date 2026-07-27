# Codex implementation prompt

You are working in the Verity repository for DAT410, an AWS re:Invent builders' session titled **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**.

Implement the repository according to `docs/VERITY-COMPLETE-CODEX-SPEC.md`.

That document is self-sufficient and authoritative. Sections 9, 10, and 11 contain the
runnable PostgreSQL DDL, the search index renderer and build lifecycle, and the canonical
retrieval SQL. Apply the schema to a disposable database and confirm it runs clean
before writing application code. Do not invent an alternative schema, and do not take
schema, model IDs, or corpus constants from anything under `reference/` — those files
carry old identifiers and are design history only.

## Non-negotiable architecture

- Amazon Aurora PostgreSQL owns materialized evidence, the versioned retrieval search index, exact/FTS/vector/fuzzy retrieval, filters and ACLs, weighted RRF, typed relationship traversal, candidate receipts, citation receipts, replay, and evaluation.
- Amazon Bedrock provides embeddings, optional reranking, and synthesis. It is not a second retrieval engine.
- CloudWatch Database Insights is a managed inspection handoff for captured plans and lock trees.
- Amazon Bedrock AgentCore Gateway is used only in Module 3 to demonstrate that the same versioned tool contracts can be exposed through a managed MCP endpoint.
- Do not add Managed Knowledge Bases, OpenSearch, Neptune, DynamoDB evidence storage, live SaaS connectors, or participant OAuth to the core path.

## Standardized fixture IDs

Use these IDs everywhere in schema seed data, API fixtures, tests, UI, docs, and expected outputs:

- `CHG-1000` confirmed cause
- `CHG-1001` ruled-out change
- `CHG-1002` safe follow-up change
- `INC-2000` canonical incident
- `INC-2001` older look-alike incident
- `LOCK-3000`, `LOCK-3001` blocking snapshots
- `CASE-4000` visible affected customer
- `CASE-4001` restricted affected customer
- `CASE-4002` explicitly unaffected customer
- `RB-5000` approved online index-build runbook
- `RB-5001` generic write-latency decoy runbook
- `COMMIT-6000` visible customer commitment
- `RUN-7000` canonical full run
- `RUN-7001` semantic-symptom run
- `RUN-7002` exact-ID run
- `RUN-7003` fuzzy-ID run
- `RUN-7004` customer-impact run

The controlled trigram typo is `CGH-1000` — a letter transposition of `CHG-1000`. It is
never a corpus identifier. Do not use the older `CHG-0100`; see `docs/ID-STANDARDIZATION.md`.

These are `external_key` values. `evidence_id` is separate immutable internal identity
(spec §9.0); the fixture seeds them to the same string, and code must not rely on that.

## Canonical question

Use the full question in the lab guide and deterministic planner:

> During `INC-2000` on `checkout-prod-01`, why did checkout writes appear to hang while reads continued? Determine whether `CHG-1000` or `CHG-1001` caused the incident, identify the customer impact visible to the current principal, explain what evidence rules out the alternative change, and cite the lock evidence and approved runbook supporting both immediate recovery and the preventive follow-up.

Compact UI form:

> Why did writes hang during `INC-2000`, which change caused it, who was affected, and what was the safe recovery?

## Three top-level UI modules

1. `Retrieve`
2. `Prove`
3. `Port tools`

Use the visual language and behavior defined in `docs/UI-FINAL-DESIGN-SPEC.md` and the static reference in `ui/final-verity-three-module-workbench.html`.

## Tool-contract ladder

Implement one canonical tool service and three thin adapters:

1. FastAPI/HTTP
2. local stdio MCP
3. AgentCore Gateway OpenAPI target

Use `contracts/openapi/verity-tools.openapi.yaml`. Every exposed operation must preserve its `operationId`; renaming one is a contract-version change.

AgentCore Gateway does **not** expose the bare `operationId`. It namespaces tools as `${targetName}___${operationId}` with three underscores, for example `verity-openapi-tools___search_evidence`. The parity normalizer strips that prefix before comparing tool identity across transports.

The OpenAPI file currently types narrower responses than spec §13 requires. Widen it to match §13 before building Module 3 — do not narrow the tool outputs to fit the file.

The core seven tools are:

- `decompose_question`
- `search_evidence`
- `follow_evidence_links`
- `compare_sources`
- `explain_ranking`
- `synthesize_cited_answer`
- `answer_with_citations`

All adapters must call the same service implementation. Do not reimplement SQL, ranking, ACLs, traversal, or synthesis inside adapters.

## Frontend constraints

- React + TypeScript + Vite.
- All API calls use `VITE_RETRIEVAL_API_URL`.
- Optional local mock mode uses `VITE_USE_MOCKS=true`.
- No remote fonts, analytics, vendor logos, or direct browser calls to Aurora, Bedrock, source systems, MCP servers, or AgentCore.
- No answer, candidate, citation, score, proof, or timing constants inside React components. Development fixtures belong in `src/lib/fixtures.ts`.
- RRF and rerank remain distinct.
- Raw FTS, cosine distance, and trigram similarity are diagnostics, never probabilities.
- ACL-filtered evidence is absent, not dimmed or disclosed.
- Wide tables scroll internally; document-level horizontal overflow is zero.

## Implementation phases

1. Migrate all fixture identifiers and tests using `docs/ID-STANDARDIZATION.md`.
2. Implement/verify the canonical service and tool response schemas.
3. Implement the three-module frontend.
4. Implement local stdio MCP as an adapter over FastAPI or shared Python service.
5. Implement the AgentCore OpenAPI target artifacts and workshop deployment documentation.
6. Implement transport parity tests using `scripts/verify_contract_parity.py`.
7. Replace illustrative plans/timings only after target-Aurora validation.
8. Run all acceptance criteria in the complete spec.

Do not silently invent missing backend behavior. Mark unsupported API fields as TODO and keep mock data in fixture files.
