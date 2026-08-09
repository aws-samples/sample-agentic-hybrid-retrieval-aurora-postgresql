\set ON_ERROR_STOP on

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'unaccent', 'pgcrypto')
ORDER BY extname;

SELECT table_schema, count(*) AS table_count
FROM information_schema.tables
WHERE table_schema IN ('mosaic','mosaic_search','mosaic_eval','mosaic_bench')
  AND table_type = 'BASE TABLE'
GROUP BY table_schema
ORDER BY table_schema;

SELECT routine_schema, count(*) AS routine_count
FROM information_schema.routines
WHERE routine_schema IN ('mosaic','mosaic_search')
GROUP BY routine_schema
ORDER BY routine_schema;

SELECT tool_name, tool_version, read_only, enabled
FROM mosaic.agent_tool_contract
ORDER BY tool_name;

SELECT
    count(*) FILTER (WHERE is_flagship) AS flagships,
    count(*) FILTER (WHERE is_retrieval_anchor) AS retrieval_anchors,
    count(*) FILTER (WHERE media_tier IN ('flagship','premium')) AS premium_products
FROM mosaic.merchandising_assignment;
