# Use Mosaic's retrieval pattern in your app

The primary takeaway is the [Mosaic Hybrid Retrieval Skill](../skills/mosaic-hybrid-retrieval/SKILL.md), including its API mapping and adaptation references. This guide is the companion map into the implementation.

Keep a full checkout of Mosaic as the runnable reference. The downloadable exercise package is a reading and adaptation kit, not a separate deployment. Dependencies are pinned in `pyproject.toml` and `uv.lock`; setup lives in the repository README. Mosaic uses Aurora PostgreSQL, including for local application development.

## Follow one request through the code

- **Catalog facts and structured attributes.** `db/sql/03_catalog.sql`. Adapt: Your entities, price or eligibility fields, and JSONB attributes.
- **Versioned source records.** `db/sql/05_evidence.sql`. Adapt: Source identity, ownership, revisions and evidence text.
- **Searchable projection.** `db/sql/06_retrieval_projection.sql`. Adapt: Weighted FTS text, stable embedding text, and reranker text.
- **Search indexes.** `db/sql/07_indexes.sql`. Adapt: GIN indexes and the vector index for your dimensions and workload.
- **FTS, fuzzy matching, vector search and filters.** `db/sql/09_search_functions.sql`. Adapt: Search language and eligibility predicates inside each candidate path.
- **Fusion arithmetic and candidate bounds.** `db/config/retrieval.yaml`, `mosaic_search.reciprocal_rank_contribution`. Adapt: Tune against your evaluation queries; retain per-arm ranks.
- **Embedding and reranking calls.** `service/embeddings.py`, `service/rerank.py`, `service/retrieval.py`. Adapt: Model identities, document text, error handling and latency budgets.
- **Tool inputs and outputs.** `db/config/agent_tool_contracts.json`, `service/models.py`. Adapt: Typed parameters, source ownership and bounded responses.
- **Tool implementation and registration.** `service/agent_tools.py`, `service/agent.py`. Adapt: `TOOL_FUNCTIONS`, focused searches, fresh evidence and application-owned state.
- **Validated cited answer.** `service/synthesis.py`. Adapt: Claim checks for your domain; allowed products, sources and revisions.
- **Saved searches and agent turns.** `db/sql/10_agent_audit.sql`, `db/sql/12_telemetry.sql`. Adapt: Correlation, retention and replay of what actually happened.

Keep volatile price and inventory fields out of embedding text. Apply them as SQL filters and include current facts in the reranker and evidence records. Re-embedding should follow a meaningful change to the text or model space, not every inventory update.

## Build the smallest useful tool

Complete [Build a retrieval tool](build-retrieval-tool.md). Its starter asks you to implement a business rule and register a typed tool; the check calls that tool against the live API and reopens its saved searches.

The example wraps `POST /api/search`, so it retains the production pipeline and its diagnostics. To move the pattern to another application, replace the catalog schema, projection and filters while preserving the returned search ID and the evidence boundary.

## Keep ranking explainable

Each candidate has a position in each retrieval list. The SQL template adds reciprocal-rank contributions and then passes a bounded pool to the reranker. Read the configured fusion constant and bounds from `db/config/retrieval.yaml`; do not copy another set of defaults into a client.

Higher RRF scores rank better within fusion. The reranker has its own score scale. Rank 1 is first in either list. Compare positions and candidate membership, not raw scores across methods or independent searches.

A reranker cannot recover an omitted candidate. Keep a test where each retrieval method contributes something the others miss, alongside exact-model and hard-filter controls.

## Give the agent an evidence boundary

Mosaic exposes five canonical agent tools:

1. `search_products` searches within the request's eligibility rules.
2. `get_product_evidence` retrieves sources for a product the run is allowed to use.
3. `compare_products` compares catalog attributes and recorded ranks.
4. `explain_retrieval` reads a saved search's ranking signals.
5. `synthesize_cited_answer` produces the validated answer from authorized products and evidence.

`AgentResponse.retrieved_evidence` carries snapshots of the records read by the tools, including those the answer did not cite. Reason groups them by product and source type. Do not fetch today's source and present it as the record an older answer read.

Specifications and reviews can answer different questions. Retain their source type, text, ID and revision. If reviews are missing or do not support the specific benefit, say so. A valid source ID proves traceability; it does not by itself prove a factual claim.

## Verify your adaptation

Use the same request before and after a change. Keep the applied filters, candidates by method, fused and final ranks, model identities, timings, evidence records and citations. Add a counterexample that must fail, such as an over-budget product or an unsupported measurement.

The existing three lab validators exercise the production path. Use `scripts/validate_lab.py` and the mission manifest for the commands and required controls. For broader quality, adapt `data/evals/canonical_queries.jsonl` and `scripts/evaluate.py` to your own query population.

Aurora continues to hold catalog facts, evidence and run records when you change the agent host. AgentCore Runtime, Gateway and persistent preference memory are separate extensions; they are not prerequisites for the retrieval pattern above.
