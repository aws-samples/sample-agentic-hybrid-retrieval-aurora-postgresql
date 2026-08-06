CREATE OR REPLACE VIEW retrieval.v_index_definitions AS
SELECT
  schemaname,
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname IN ('evidence', 'retrieval', 'proof')
ORDER BY schemaname, tablename, indexname;

CREATE OR REPLACE FUNCTION retrieval.configure_ann_runtime(
  p_ef_search integer,
  p_iterative_scan text,
  p_trgm_threshold real DEFAULT 0.3,
  p_max_scan_tuples integer DEFAULT 20000,
  p_scan_mem_multiplier numeric DEFAULT 2
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_ef_search IS NULL OR p_ef_search < 1 OR p_ef_search > 1000 THEN
    RAISE EXCEPTION 'hnsw.ef_search must be between 1 and 1000';
  END IF;

  IF p_iterative_scan NOT IN ('off', 'strict_order', 'relaxed_order') THEN
    RAISE EXCEPTION
      'hnsw.iterative_scan must be off, strict_order, or relaxed_order';
  END IF;

  IF p_trgm_threshold < 0 OR p_trgm_threshold > 1 THEN
    RAISE EXCEPTION 'pg_trgm.similarity_threshold must be between 0 and 1';
  END IF;

  IF p_max_scan_tuples < 1 OR p_scan_mem_multiplier < 1 THEN
    RAISE EXCEPTION
      'HNSW scan bounds must be positive: max_scan_tuples=% scan_mem_multiplier=%',
      p_max_scan_tuples,
      p_scan_mem_multiplier;
  END IF;

  PERFORM set_config('hnsw.ef_search', p_ef_search::text, true);
  PERFORM set_config('hnsw.iterative_scan', p_iterative_scan, true);
  PERFORM set_config('hnsw.max_scan_tuples', p_max_scan_tuples::text, true);
  PERFORM set_config(
    'hnsw.scan_mem_multiplier',
    p_scan_mem_multiplier::text,
    true
  );
  PERFORM set_config(
    'pg_trgm.similarity_threshold',
    p_trgm_threshold::text,
    true
  );
END
$$;
