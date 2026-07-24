CREATE OR REPLACE VIEW retrieval.v_index_definitions AS
SELECT
  schemaname,
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname IN ('casework', 'retrieval', 'proof')
ORDER BY schemaname, tablename, indexname;

CREATE OR REPLACE FUNCTION retrieval.configure_ann_runtime(
  p_ef_search integer,
  p_iterative_scan text
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

  PERFORM set_config('hnsw.ef_search', p_ef_search::text, true);
  PERFORM set_config('hnsw.iterative_scan', p_iterative_scan, true);
END
$$;
