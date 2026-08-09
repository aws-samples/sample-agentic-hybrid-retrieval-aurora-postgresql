# Agent tool contracts

The agent orchestrates deterministic Aurora-backed tools; it does not replace retrieval.

## Recommended read-only tools

### `search_catalog`

Inputs: query, structured filters, top K, retrieval profile.
Outputs: fused candidates, per-channel provenance, eligibility, and media.

### `compare_products`

Inputs: product IDs and comparison criteria.
Outputs: typed attribute matrix, missing values, and decisive differences.

### `get_product_evidence`

Inputs: product ID, evidence types, query, top K.
Outputs: supporting evidence chunks with source metadata and similarity.

### `explain_recommendation`

Inputs: query, product ID, candidate provenance, evidence IDs.
Outputs: concise rationale, matched requirements, trade-offs, and citations.

Every call is recorded in `mosaic.agent_tool_event`, including tool version, input/output payload, duration, outcome, and linked search event.
