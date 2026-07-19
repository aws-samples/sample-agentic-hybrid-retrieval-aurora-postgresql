-- pgvector 0.8 capabilities on the retrieval corpus.
--
-- Three beats a workshop attendee can run and measure against the baseline
-- float32 HNSW index (idx_chunks_embedding_hnsw), all additive and idempotent:
--
--   1. iterative_scan  — pgvector 0.8's answer to filtered-search recall loss.
--      When a WHERE filter prunes most rows, a fixed ef_search can return fewer
--      than p_limit rows; relaxed_order iterative scan keeps scanning the graph
--      until the limit is met. ops.vector_search_iterative exposes it.
--   2. halfvec         — 16-bit half-precision vectors. Half the storage and a
--      smaller HNSW index at a tiny recall cost. ops.vector_search_halfvec runs
--      cosine over a halfvec HNSW index.
--   3. binary_quantize — 1-bit-per-dimension quantization + Hamming distance for
--      a cheap coarse pass, then exact float32 cosine rerank of the shortlist.
--      ops.vector_search_binary_two_pass is the two-pass recall/latency trade.
--
-- ops.v_index_sizes reports the on-disk size of each vector index so the storage
-- trade is a real measured number, not a claim.

-- --------------------------------------------------------------------------
-- halfvec HNSW index. WHERE embedding IS NOT NULL matches the float32 index so
-- the two are directly comparable. The cast is immutable, so pgvector can build
-- the index straight from the float32 column.
-- --------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw_halfvec
  ON ops.object_chunks
  USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE embedding IS NOT NULL;

-- binary HNSW index over the 1-bit quantization, Hamming distance. This backs the
-- coarse pass of the two-pass search.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw_binary
  ON ops.object_chunks
  USING hnsw ((binary_quantize(embedding)::bit(1024)) bit_hamming_ops)
  WHERE embedding IS NOT NULL;

-- --------------------------------------------------------------------------
-- Beat 1: iterative scan. Same cosine search as ops.vector_search, but with
-- hnsw.iterative_scan = relaxed_order set for the function's scope so a
-- selective filter cannot starve the result below p_limit. Compare row counts
-- against ops.vector_search under a narrow p_source_systems / p_project_key
-- filter to see the recall recovery.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.vector_search_iterative(
  p_query_embedding vector(1024),
  p_source_systems text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_component text DEFAULT NULL,
  p_limit int DEFAULT 20
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  external_id text,
  title text,
  score numeric
)
LANGUAGE sql
STABLE
SET hnsw.iterative_scan = relaxed_order
AS $$
  SELECT c.chunk_id, o.object_id, o.source_system, o.external_id, o.title,
         (1 - (c.embedding <=> p_query_embedding))::numeric AS score
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  WHERE c.embedding IS NOT NULL AND p_query_embedding IS NOT NULL
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
  ORDER BY c.embedding <=> p_query_embedding ASC
  LIMIT p_limit;
$$;

-- --------------------------------------------------------------------------
-- Beat 2: halfvec search. Cosine over the halfvec HNSW index. Casting the query
-- vector to halfvec(1024) makes the ORDER BY use idx_chunks_embedding_hnsw_halfvec.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.vector_search_halfvec(
  p_query_embedding vector(1024),
  p_source_systems text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_limit int DEFAULT 20
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  external_id text,
  title text,
  score numeric
)
LANGUAGE sql
STABLE
AS $$
  SELECT c.chunk_id, o.object_id, o.source_system, o.external_id, o.title,
         (1 - (c.embedding::halfvec(1024) <=> p_query_embedding::halfvec(1024)))::numeric AS score
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  WHERE c.embedding IS NOT NULL AND p_query_embedding IS NOT NULL
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
  ORDER BY c.embedding::halfvec(1024) <=> p_query_embedding::halfvec(1024) ASC
  LIMIT p_limit;
$$;

-- --------------------------------------------------------------------------
-- Beat 3: binary two-pass. A cheap Hamming coarse pass over the binary index
-- gathers p_coarse_limit candidates, then exact float32 cosine reranks them to
-- p_limit. This is the recall/latency trade: the coarse multiplier
-- (p_coarse_limit / p_limit) buys back the recall the 1-bit quantization loses.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.vector_search_binary_two_pass(
  p_query_embedding vector(1024),
  p_source_systems text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_limit int DEFAULT 20,
  p_coarse_limit int DEFAULT 200
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  external_id text,
  title text,
  score numeric,
  hamming_distance numeric
)
LANGUAGE sql
STABLE
AS $$
  WITH coarse AS (
    SELECT c.chunk_id, c.object_id, c.embedding,
           (binary_quantize(c.embedding)::bit(1024) <~> binary_quantize(p_query_embedding)::bit(1024))::numeric AS hamming_distance
    FROM ops.object_chunks c
    JOIN ops.source_objects o ON o.object_id = c.object_id
    WHERE c.embedding IS NOT NULL AND p_query_embedding IS NOT NULL
      AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
      AND (p_project_key IS NULL OR o.project_key = p_project_key)
    ORDER BY binary_quantize(c.embedding)::bit(1024) <~> binary_quantize(p_query_embedding)::bit(1024) ASC
    LIMIT p_coarse_limit
  )
  SELECT coarse.chunk_id, o.object_id, o.source_system, o.external_id, o.title,
         (1 - (coarse.embedding <=> p_query_embedding))::numeric AS score,
         coarse.hamming_distance
  FROM coarse
  JOIN ops.source_objects o ON o.object_id = coarse.object_id
  ORDER BY coarse.embedding <=> p_query_embedding ASC
  LIMIT p_limit;
$$;

-- --------------------------------------------------------------------------
-- On-disk size of every vector index, so the storage trade is measured, not
-- claimed. float32 vs halfvec vs binary over the same rows.
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_index_sizes AS
SELECT
  c.relname AS index_name,
  CASE
    WHEN c.relname LIKE '%halfvec' THEN 'halfvec (16-bit)'
    WHEN c.relname LIKE '%binary'  THEN 'binary (1-bit)'
    WHEN c.relname LIKE '%hnsw'    THEN 'float32 (32-bit)'
    ELSE 'other'
  END AS precision,
  pg_size_pretty(pg_relation_size(c.oid)) AS index_size,
  pg_relation_size(c.oid) AS index_size_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
  AND c.relkind = 'i'
  AND c.relname LIKE 'idx_chunks_embedding_hnsw%'
ORDER BY index_size_bytes DESC;
