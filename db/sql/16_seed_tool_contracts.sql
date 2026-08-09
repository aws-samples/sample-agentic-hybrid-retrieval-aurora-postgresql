\set ON_ERROR_STOP on

INSERT INTO mosaic.agent_tool_contract (
    tool_name, tool_version, description, input_schema, output_schema, read_only
)
VALUES
(
    'search_catalog', '1.0',
    'Hybrid product retrieval with FTS, pg_trgm, HNSW, filters, and RRF provenance.',
    '{"type":"object","required":["query"],"properties":{"query":{"type":"string"},"filters":{"type":"object"},"top_k":{"type":"integer","minimum":1,"maximum":100}}}'::jsonb,
    '{"type":"object","required":["results"],"properties":{"results":{"type":"array"},"diagnostics":{"type":"object"}}}'::jsonb,
    true
),
(
    'compare_products', '1.0',
    'Compare a bounded product shortlist using typed attributes and decisive criteria.',
    '{"type":"object","required":["product_ids"],"properties":{"product_ids":{"type":"array","items":{"type":"integer"},"minItems":2,"maxItems":8},"criteria":{"type":"array","items":{"type":"string"}}}}'::jsonb,
    '{"type":"object","required":["products","comparison"],"properties":{"products":{"type":"array"},"comparison":{"type":"object"}}}'::jsonb,
    true
),
(
    'get_product_evidence', '1.0',
    'Retrieve supporting specifications, reviews, Q&A, summaries, and benchmarks for a product.',
    '{"type":"object","required":["product_id","query"],"properties":{"product_id":{"type":"integer"},"query":{"type":"string"},"evidence_types":{"type":"array","items":{"type":"string"}},"top_k":{"type":"integer","minimum":1,"maximum":20}}}'::jsonb,
    '{"type":"object","required":["evidence"],"properties":{"evidence":{"type":"array"}}}'::jsonb,
    true
),
(
    'explain_recommendation', '1.0',
    'Produce an evidence-backed explanation from existing retrieval provenance and evidence IDs.',
    '{"type":"object","required":["query","product_id","provenance"],"properties":{"query":{"type":"string"},"product_id":{"type":"integer"},"provenance":{"type":"object"},"evidence_ids":{"type":"array","items":{"type":"integer"}}}}'::jsonb,
    '{"type":"object","required":["rationale","matched_requirements","tradeoffs"],"properties":{"rationale":{"type":"string"},"matched_requirements":{"type":"array"},"tradeoffs":{"type":"array"},"citations":{"type":"array"}}}'::jsonb,
    true
)
ON CONFLICT (tool_name, tool_version) DO UPDATE SET
    description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    output_schema = EXCLUDED.output_schema,
    read_only = EXCLUDED.read_only,
    enabled = true;

-- The application's Strands tools. `search_catalog`, `compare_products`,
-- `get_product_evidence`, and `explain_recommendation` above describe the
-- reference tool surface; these are the names this repository actually
-- registers. `mosaic.agent_tool_event` has a composite foreign key to
-- (tool_name, tool_version), so an unregistered tool cannot be audited and its
-- insert would fail at runtime.
INSERT INTO mosaic.agent_tool_contract (
    tool_name, tool_version, description, input_schema, output_schema, read_only
)
VALUES
(
    'search_products', '1.0',
    'Hybrid product retrieval over mosaic_search with FTS, pg_trgm, HNSW, SQL filters, and RRF provenance.',
    '{"type":"object","required":["query"],"properties":{"query":{"type":"string"},"domain":{"type":"string"},"category_key":{"type":"string"},"brand":{"type":"string"},"availability":{"type":"string"},"in_stock_only":{"type":"boolean"},"min_price_cents":{"type":"integer","minimum":0},"max_price_cents":{"type":"integer","minimum":0},"min_rating":{"type":"number","minimum":0,"maximum":5},"attributes":{"type":"object"},"limit":{"type":"integer","minimum":1,"maximum":12}}}'::jsonb,
    '{"type":"object","required":["ok"],"properties":{"ok":{"type":"boolean"},"search_event_id":{"type":"string"},"products":{"type":"array"},"diagnostics":{"type":"object"}}}'::jsonb,
    true
),
(
    'explain_retrieval', '1.0',
    'Replay persisted arm ranks, scores, fusion contributions, and reranker order for one search event.',
    '{"type":"object","required":["search_event_id"],"properties":{"search_event_id":{"type":"string","format":"uuid"}}}'::jsonb,
    '{"type":"object","required":["ok"],"properties":{"ok":{"type":"boolean"},"search_event":{"type":"object"},"candidates":{"type":"array"}}}'::jsonb,
    true
),
(
    'synthesize_cited_answer', '1.0',
    'Compose the answer of record from retrieved products, requiring a citation for every product claim.',
    '{"type":"object","required":["product_ids"],"properties":{"product_ids":{"type":"array","items":{"type":"integer"}},"question":{"type":"string"}}}'::jsonb,
    '{"type":"object","required":["ok"],"properties":{"ok":{"type":"boolean"},"answer":{"type":"string"},"citations":{"type":"array"}}}'::jsonb,
    true
)
ON CONFLICT (tool_name, tool_version) DO UPDATE
SET description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    output_schema = EXCLUDED.output_schema,
    read_only = EXCLUDED.read_only;
