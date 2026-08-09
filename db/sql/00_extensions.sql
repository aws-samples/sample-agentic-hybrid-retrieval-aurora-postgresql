\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    vector_version text;
BEGIN
    SELECT extversion INTO vector_version
    FROM pg_extension
    WHERE extname = 'vector';

    RAISE NOTICE 'Mosaic schema installing with pgvector version %', vector_version;
    IF split_part(vector_version, '.', 1)::integer = 0
       AND split_part(vector_version, '.', 2)::integer < 8 THEN
        RAISE WARNING 'pgvector % predates iterative HNSW scans; the advanced filtered-ANN lab expects 0.8.0 or later', vector_version;
    END IF;
END
$$;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'unaccent', 'pgcrypto')
ORDER BY extname;
