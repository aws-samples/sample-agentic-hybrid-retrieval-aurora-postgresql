# Data dictionary

## `mosaic` schema

### `brand`
Synthetic catalog brand dimension. `brand_key` is stable and machine-friendly; `display_name` is presentation text.

### `category`
Hierarchical taxonomy. `category_path` is the human-readable breadcrumb copied into the retrieval projection.

### `product`
Stable product identity and content. `canonical_group_id` groups color/size/storage variants for result diversity. `challenge_cohorts` identifies deliberate eval cases such as typo targets, hard negatives, and selective filters.

### `product_offer`
Current commerce state. Price, stock, rating, review count, popularity, freshness, sponsorship, and other volatile values are separated from semantic product content.

### `merchandising_assignment`
Controls the visual Shop experience: media tier, page, position, display title, flagship status, and retrieval-anchor status. It never removes a product from the full search corpus.

### `media_asset` / `product_media`
Physical image metadata plus product-specific roles, crop anchors, and brand-mark zones.

### `product_evidence`
Supporting specification, review, Q&A, expert, guide, or benchmark text with its own FTS document and embedding.

### `agent_*` / `rerank_*`
Agent tool contracts, sessions, turns, tool-call audit, rerank invocation metadata, and per-product rerank outputs.

### `search_event` / `search_result_event`
Query-level observability, result provenance, and user interaction telemetry.

## `mosaic_search` schema

### `product_document`
One denormalized row per searchable product. It contains:

- common filter columns beside the vector
- weighted FTS fields
- trigram document
- product semantic document
- reranker document
- HNSW embedding
- source scores and merchandising flags needed by the UI

## `mosaic_eval` schema

- `query`: eval prompt, intent, filters, expected techniques
- `judgment`: graded relevance truth
- `run`: retrieval/reranker configuration and dataset identity
- `result`: ranked output with source scores and provenance
- `metric`: Recall, MRR, nDCG, latency, and sliced metrics

## `mosaic_bench` schema

- `profile`: scale/index/runtime/filter configuration
- `run`: one benchmark execution and environment
- `measurement`: latency, recall, QPS, size, build time, plans
- `vector_item`: physical synthetic vector table for scale experiments
