# Documentation map

Mosaic is a product discovery application built around three visible
surfaces: Discover, Shop, and Playground. Participants work through three
required labs on top of it: Lab 1 - Build hybrid retrieval, Lab 2 - Fuse,
rerank, and inspect, and Lab 3 - Build the retrieval agent. The documents
below cover the dataset, the retrieval and ranking mechanics, the UI and API
contracts, and the release and evaluation gates that keep the session
honest.

| Document | Purpose |
|---|---|
| `workshop.md` (repo root) | Co-presenter brief: story, three-lab journey, how to read a run |
| `architecture.md` | Runtime and offline architecture |
| `catalog-spec.md` | Dataset taxonomy, schema, attributes, and challenge cohorts |
| `category-plate-prompts.md` | Prompt set for category-plate imagery |
| `data-generation.md` | Regeneration, reviews, embeddings, and scale extension |
| `retrieval-curriculum.md` | Builder-session learning flow |
| `pg-trgm-lab.md` | Typo-tolerance lesson and evaluation |
| `fusion-rerank.md` | Candidate fusion, deterministic filters, and reranking |
| `hnsw-lab.md` | Recall/latency/filter/build experiment design |
| `benchmark-methodology.md` | Reproducible measurement rules |
| `evaluation-plan.md` | Offline metrics and ablations |
| `query-catalog.md` | Curated demonstration queries |
| `lab-golden-queries.md` | Three lab experiments, five proof anchors, and recovery |
| `ui-design-system.md` | Maroon/ivory product-discovery and retrieval-evidence design language |
| `ui-screen-spec.md` | UI screen, component, and payload contracts |
| `api-contract.md` | Search API request/response contract |
| `telemetry-contract.md` | Aurora telemetry schema, portable timeline, and optional AgentCore projection |
| `mcp-interoperability.md` | Optional interoperability contract and isolated runtime |
| `skill-composition.md` | Pointer to the self-contained participant skill's composition, HTTP mapping, and adaptation references |
| `aurora-deployment.md` | Aurora setup and operational sequence |
| `production-readiness.md` | Relevance, data, performance, governance, and UX checklist |
| `product-image-strategy.md` | Scalable realistic-image approach |
| `image-generation-guide.md` | Image-generation and ingestion workflow |
| `image-prompts-category-plates.md` | Art direction for category-plate generation |
| `media-generation-batches.md` | Generated media batch inventory |
| `media-regeneration-batches.md` | Controlled media regeneration workflow |
| `media-shot-list.md` | Manifest-derived outstanding product image work |
| `instructor-guide.md` | Facilitation narrative and failure-safe plan |
| `session-abstract.md` | Session title, abstract, and audience framing |
| `intentional-gaps.md` | Deliberate starter gaps and their recovery contracts |
| `implementation-status.md` | What is complete versus environment-dependent |
| `house-standards.md` | Binding assertions, probes, and release-gate standards |
| `rewrite-losses.md` | Retired predecessor scope and non-recoverable history |
