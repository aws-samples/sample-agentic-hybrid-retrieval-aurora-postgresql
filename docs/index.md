# Documentation map

Workshop participants should start with [Start Here](../START_HERE.md).
The remaining guides are grouped by the work they support.

## Participants

| Guide | Purpose |
|---|---|
| [Start Here](../START_HERE.md) | Open your prepared environment and follow the three required labs |
| [Use the pattern in your app](use-in-your-app.md) | Take-home map for schema, SQL, ranking and agent tools |
| [Run Mosaic in your own account](run-in-your-own-account.md) | Outside an event: what the stack creates, dated list prices, the catalog build, deploy and tear-down |
| [Mosaic skill](skill-composition.md) | Portable workflow, HTTP mapping and adaptation references |

## Developers

| Guide | Purpose |
|---|---|
| [Development guide](development.md) | Application setup, validation and publishing links |
| [Architecture](architecture.md) | Runtime and catalog restore pipeline |
| [Database facts](postgres-18.md) | Engine, extensions and the retrieval path |
| [Build a retrieval tool](build-retrieval-tool.md) | Filters, typed tools and saved searches |
| [Fuzzy matching lab](pg-trgm-lab.md) | Real identifier recovery and production SQL inspection |
| [HNSW experiment design](hnsw-lab.md) | Optional performance exercise on the served catalog; anchors, ground truth and measurement path |
| [Hybrid search design](hybrid-search-design.md) | One question through three checks: find, order and justify from records |
| [Fusion and reranking](fusion-rerank.md) | Candidate fusion, deterministic filters and reranking |
| [API contract](api-contract.md) | Search request and response contracts |
| [Security boundaries](security-boundaries.md) | Workshop access, evidence authority and production adaptation |
| [UI design system](ui-design-system.md) | Visual language and component rules |
| [UI screen specification](ui-screen-spec.md) | Screen, component and payload contracts |
| [Telemetry contract](telemetry-contract.md) | Aurora telemetry and optional AgentCore export |
| [MCP interoperability](mcp-interoperability.md) | Optional interoperability contract and isolated runtime |
| [AgentCore Runtime](agentcore-runtime.md) | Required for Lab 3: managed deployment of the Retrieval agent and its SQL tools through Runtime and Gateway |
| [Session memory](session-memory.md) | Optional AgentCore events, memory strategies and verification |
| [House standards](house-standards.md) | Binding rules for assertions, probes and release gates |

## Facilitators and release operators

| Guide | Purpose |
|---|---|
| [Workshop brief](../workshop.md) | Presenter brief: the hour, how to open with Alex, each lab's teaching point and how to help without erasing the exercise |
| [Instructor guide](instructor-guide.md) | Facilitation narrative and recovery plan |
| [Event readiness](event-readiness.md) | Each box's readiness record and the per-account table to read before an event |
| [Lab design](l400-lab-design.md) | Participant page shape, graded work and acceptance boundaries |
| [Retrieval curriculum](retrieval-curriculum.md) | Builder-session learning flow |
| [Abstract delivery map](abstract-delivery-map.md) | Required work and optional extensions |
| [Session abstract](session-abstract.md) | Title, abstract and audience |
| [Lab queries](lab-golden-queries.md) | Required experiments, proof anchors and recovery |
| [Intentional gaps](intentional-gaps.md) | Defects in the starting code and their recovery contracts |
| [Artifacts and restore](../ARTIFACTS.md) | Pinned real products, saved vectors and Aurora connection notes |
| [Aurora deployment](aurora-deployment.md) | Provisioning and operational sequence |
| [Release readiness](../READINESS.md) | Required source and deployment gates |
| [Rehearsal runbook](rehearsal-runbook.md) | Clean-account recorder and bounded load exercise |
| [Fresh-account evidence](evidence/fresh-account-2026-09-26.md) | Dated record, 26 September 2026: measured deployment acceptance and remaining rehearsal work |
| [Remediation status](remediation-status.md) | Superseded record, 26 September 2026: fixes, verification scope and feedback; current state is in [READINESS.md](../READINESS.md) |
| [Implementation status](implementation-status.md) | Implemented behavior and remaining certification |
| [Evaluation plan](evaluation-plan.md) | Current and historical query sets, metrics and measurement rules |
| [Benchmark methodology](benchmark-methodology.md) | Reproducible measurement rules |
| [Production adaptation checklist](production-readiness.md) | Relevance, data, performance, governance and UX |
| [Parking lot](mosaic-parking-lot.md) | Record, 9 September 2026: optional product ideas, written before Runtime and Gateway shipped |
| [Real-catalog examples](real-catalog-exercise-library.md) | Historical record: secondary examples measured on the retired `reviews-2023-500k-v1` catalog |

## Maintainer references

| Guide | Purpose |
|---|---|
| [Saved scale benchmarks](current-scale-benchmarks.md) | Measured on the served catalog on 26 September 2026: recall, filters, exact baseline, index build |
| [Instance comparison](hardware-comparison-2026-09-26.md) | db.r8g.2xlarge against db.r8gd.2xlarge on restored copies of the catalog, default and small-memory pairs |
| [Truth register (append-only record)](rewrite-losses.md) | Retired predecessor scope and non-recoverable history |
| [Catalog source assessment](catalog-source-assessment.md) | Source review of the real catalog, with its 22 and 26 September 2026 status updates |
| [Reviewed exercises](reviewed-exercises-2026-09-22.md) | Historical record: reviewed headphone, chair and monitor comparisons measured on the retired `reviews-2023-500k-v1` catalog |
| [Monitor image prompts](monitor-image-prompts.md) | Image provenance record, 19 September 2026: the prompts and delivered sizes for the generated monitor images |
