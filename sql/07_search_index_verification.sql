CREATE OR REPLACE VIEW retrieval.v_embedding_spaces AS
SELECT
  chunk.embedding_model,
  vector_dims(chunk.embedding) AS dimensions,
  count(*) AS chunks,
  min(chunk.created_at) AS first_created_at,
  max(chunk.created_at) AS last_created_at
FROM retrieval.chunks chunk
JOIN retrieval.documents document
  ON document.document_version_id = chunk.document_version_id
WHERE document.is_current
  AND document.index_state = 'ready'
  AND chunk.is_current
  AND chunk.embedding_state = 'ready'
  AND chunk.embedding IS NOT NULL
GROUP BY chunk.embedding_model, vector_dims(chunk.embedding);

CREATE OR REPLACE FUNCTION retrieval.assert_search_index_ready()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  health retrieval.v_search_index_health%ROWTYPE;
  embedding_space_count integer;
  full_drift_issues integer;
BEGIN
  SELECT * INTO health FROM retrieval.v_search_index_health;
  SELECT count(*) INTO embedding_space_count FROM retrieval.v_embedding_spaces;
  SELECT count(*) INTO full_drift_issues FROM retrieval.v_search_index_drift;

  IF health.source_documents = 0 THEN
    RETURN jsonb_build_object(
      'status', 'awaiting_incident',
      'source_documents', 0,
      'current_documents', 0,
      'current_chunks', 0,
      'ready_embeddings', 0,
      'drift_issues', full_drift_issues,
      'last_indexed_at', NULL,
      'embedding_spaces', '[]'::jsonb
    );
  END IF;

  IF full_drift_issues <> 0 THEN
    RAISE EXCEPTION 'search index has % drift issue(s)', full_drift_issues;
  END IF;

  IF health.current_documents <> health.source_documents THEN
    RAISE EXCEPTION
      'current document count (%) does not match source document count (%)',
      health.current_documents,
      health.source_documents;
  END IF;

  IF health.current_chunks = 0 OR health.ready_embeddings <> health.current_chunks THEN
    RAISE EXCEPTION
      'embedding readiness mismatch: chunks=% ready_embeddings=%',
      health.current_chunks,
      health.ready_embeddings;
  END IF;

  IF embedding_space_count <> 1 THEN
    RAISE EXCEPTION
      'expected exactly one current embedding space, found %',
      embedding_space_count;
  END IF;

  RETURN jsonb_build_object(
    'status', 'ready',
    'source_documents', health.source_documents,
    'current_documents', health.current_documents,
    'current_chunks', health.current_chunks,
    'ready_embeddings', health.ready_embeddings,
    'drift_issues', full_drift_issues,
    'last_indexed_at', health.last_indexed_at,
    'embedding_spaces', (
      SELECT jsonb_agg(to_jsonb(space))
      FROM retrieval.v_embedding_spaces space
    )
  );
END
$$;
