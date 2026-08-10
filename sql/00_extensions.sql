\set ON_ERROR_STOP on

-- DEPRECATED: the `catalog.*` tree. The application does not read this schema;
-- `service/retrieval.py` queries `mosaic` and `mosaic_search` (see db/sql/).
-- Deleted by Phase 2 Unit E. See docs/rewrite-losses.md for what the rewrite
-- dropped and docs/superpowers/specs/ for the Phase 2 design.
-- Do not add features here. Do not point a lab at it.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'unaccent', 'pgcrypto')
ORDER BY extname;
