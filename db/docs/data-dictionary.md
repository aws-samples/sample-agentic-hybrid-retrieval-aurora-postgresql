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

### `product_listing`
One denormalized row per source listing, loaded once by the restore. It contains:

- common filter columns beside the vector
- weighted FTS fields (`search_document`)
- trigram document (`trigram_text`)
- product semantic document (`embedding_text`)
- HNSW embedding (`embedding`, `vector(1024)`)

Its indexes, in `07_indexes.sql`, are `product_search_fts_idx` (GIN),
`product_search_trigram_idx` (GIN, `gin_trgm_ops`), `product_search_vector_idx`
(HNSW, cosine), `product_search_kind_idx` and `product_search_public_id_idx`.

### `product_listing_view`
What every search function reads: `product_listing` with the shop's product IDs
(an offset of 1,000,000), the reranker document and each listing's recorded
source price from `source_price`. PostgreSQL uses `product_listing`'s indexes
through it.

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
