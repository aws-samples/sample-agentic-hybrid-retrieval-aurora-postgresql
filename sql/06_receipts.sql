CREATE OR REPLACE VIEW proof.v_answer_receipts AS
SELECT
  answer.run_id,
  answer.question,
  answer.answer_text,
  answer.synthesis_mode,
  answer.model_id,
  answer.model_transport,
  answer.input_tokens,
  answer.output_tokens,
  answer.created_at,
  coalesce(
    jsonb_agg(
      jsonb_build_object(
        'citation_number', citation.citation_number,
        'evidence_id', citation.evidence_id,
        'external_key', item.external_key,
        'title', item.title,
        'source_uri', citation.source_uri,
        'source_revision', citation.source_revision,
        'quote_text', citation.quote_text,
        'claim', citation.claim
      )
      ORDER BY citation.citation_number
    ) FILTER (WHERE citation.citation_number IS NOT NULL),
    '[]'::jsonb
  ) AS citations
FROM proof.agent_answers answer
LEFT JOIN proof.answer_citations citation ON citation.run_id = answer.run_id
LEFT JOIN casework.evidence_items item ON item.evidence_id = citation.evidence_id
GROUP BY answer.run_id;

CREATE OR REPLACE VIEW proof.v_candidate_receipts AS
SELECT
  candidate.run_id,
  candidate.result_rank,
  candidate.evidence_id,
  item.external_key,
  item.title,
  item.evidence_kind,
  candidate.text_rank,
  candidate.vector_score,
  candidate.trigram_score,
  candidate.text_position,
  candidate.vector_position,
  candidate.trigram_position,
  candidate.rrf_score,
  candidate.rerank_score,
  candidate.final_score,
  candidate.explanation,
  candidate.evidence_snapshot
FROM proof.retrieval_candidates candidate
JOIN casework.evidence_items item ON item.evidence_id = candidate.evidence_id;

CREATE OR REPLACE FUNCTION proof.validate_answer_citations(p_run_id uuid)
RETURNS TABLE (
  citation_number integer,
  evidence_id uuid,
  is_valid boolean,
  issue text
)
LANGUAGE sql
STABLE
AS $$
SELECT
  citation.citation_number,
  citation.evidence_id,
  (
    citation.source_uri = document.source_uri
    AND citation.source_revision = document.source_revision
    AND position(citation.quote_text IN chunk.chunk_text) > 0
  ) AS is_valid,
  CASE
    WHEN citation.source_uri <> document.source_uri THEN 'source_uri_mismatch'
    WHEN citation.source_revision <> document.source_revision THEN 'source_revision_mismatch'
    WHEN position(citation.quote_text IN chunk.chunk_text) = 0 THEN 'quote_not_in_chunk'
    ELSE NULL
  END AS issue
FROM proof.answer_citations citation
JOIN retrieval.documents document
  ON document.document_version_id = citation.document_version_id
JOIN retrieval.chunks chunk
  ON chunk.chunk_version_id = citation.chunk_version_id
WHERE citation.run_id = p_run_id
ORDER BY citation.citation_number
$$;
