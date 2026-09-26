# Documentation map

Workshop participants should start with [Start Here](../START_HERE.md).
The remaining guides are grouped by the work they support.

## Participants

| Guide | Purpose |
|---|---|
| [Start Here](../START_HERE.md) | Open your prepared environment and follow the three required labs |
| [Use the pattern in your app](use-in-your-app.md) | Take-home map for schema, SQL, ranking and agent tools |
| [Real-catalog examples](real-catalog-exercise-library.md) | Measured examples and evidence limits |
| [Mosaic skill](skill-composition.md) | Portable workflow, HTTP mapping and adaptation references |

## Developers

| Guide | Purpose |
|---|---|
| [Development guide](development.md) | Application setup, validation and publishing links |
| [Architecture](architecture.md) | Runtime and catalog restore pipeline |
| [Database facts](postgres-18.md) | Engine, extensions and the retrieval path |
| [Build a retrieval tool](build-retrieval-tool.md) | Filters, typed tools and saved searches |
| [Typo-tolerance lab](pg-trgm-lab.md) | Real identifier recovery and production SQL inspection |
| [HNSW experiment design](hnsw-lab.md) | Optional performance exercise on the served catalog; anchors, ground truth and measurement path |
| [Fusion and reranking](fusion-rerank.md) | Candidate fusion, deterministic filters and reranking |
| [API contract](api-contract.md) | Search request and response contracts |
| [Security boundaries](security-boundaries.md) | Workshop access, evidence authority and production adaptation |
| [UI design system](ui-design-system.md) | Visual language and component rules |
| [UI screen specification](ui-screen-spec.md) | Screen, component and payload contracts |
| [Telemetry contract](telemetry-contract.md) | Aurora telemetry and optional AgentCore export |
| [MCP interoperability](mcp-interoperability.md) | Optional interoperability contract and isolated runtime |
| [AgentCore Runtime](agentcore-runtime.md) | Optional managed deployment of the API and agent process |
| [Session memory](session-memory.md) | Optional AgentCore events, memory strategies and verification |
| [House standards](house-standards.md) | Binding rules for assertions, probes and release gates |

## Facilitators and release operators

| Guide | Purpose |
|---|---|
| [Workshop brief](../workshop.md) | Story, three-lab journey and how to read a run |
| [Instructor guide](instructor-guide.md) | Facilitation narrative and recovery plan |
| [Lab design](l400-lab-design.md) | Participant page shape, graded work and acceptance boundaries |
| [Retrieval curriculum](retrieval-curriculum.md) | Builder-session learning flow |
| [Abstract delivery map](abstract-delivery-map.md) | Required work and optional extensions |
| [Session abstract](session-abstract.md) | Title, abstract and audience |
| [Lab queries](lab-golden-queries.md) | Required experiments, proof anchors and recovery |
| [Intentional gaps](intentional-gaps.md) | Starter defects and their recovery contracts |
| [Artifacts and restore](../ARTIFACTS.md) | Pinned real products, saved vectors and Aurora connection notes |
| [Aurora deployment](aurora-deployment.md) | Provisioning and operational sequence |
| [Workshop Studio setup](workshop-studio-setup.md) | First-time setup and cloning both repositories |
| [Workshop Studio publishing](workshop-studio-publishing.md) | Repin, validate, sync assets, push and verify the build |
| [Release readiness](../READINESS.md) | Required source and deployment gates |
| [Rehearsal runbook](rehearsal-runbook.md) | Clean-account recorder and bounded load exercise |
| [Fresh-account evidence](evidence/fresh-account-2026-09-26.md) | Measured deployment acceptance and remaining rehearsal work |
| [Remediation status](remediation-status.md) | Completed fixes, verification scope and outstanding feedback |
| [Implementation status](implementation-status.md) | Implemented behavior and remaining certification |
| [Evaluation plan](evaluation-plan.md) | Current and historical query sets, metrics and measurement rules |
| [Benchmark methodology](benchmark-methodology.md) | Reproducible measurement rules |
| [Production adaptation checklist](production-readiness.md) | Relevance, data, performance, governance and UX |
| [Parking lot](mosaic-parking-lot.md) | Remaining product ideas |

## Historical fixtures and maintainer references

| Guide | Purpose |
|---|---|
| [Historical fixture boundary](../data/full/README.md) | Why synthetic files remain and how their commands are guarded |
| [Synthetic catalog specification](catalog-spec.md) | Historical taxonomy, attributes and challenge cohorts |
| [Synthetic data generation](data-generation.md) | Historical fixture regeneration and embedding tools |
| [Historical query catalog](query-catalog.md) | Original synthetic demonstration requests |
| [Saved scale benchmarks](current-scale-benchmarks.md) | Measured on the served catalog on 26 September 2026: recall, filters, exact baseline, index build |
| [Historical image strategy](product-image-strategy.md) | Synthetic cohort media design |
| [Media regeneration](media-regeneration-batches.md) | Historical cohort media workflow |
| [Media shot list](media-shot-list.md) | Historical product-image inventory |
| [Focused product prompts](hnsw-focused-product-prompts.md) | Historical synthetic cohort authoring |
| [Rewrite losses](rewrite-losses.md) | Retired predecessor scope and non-recoverable history |
