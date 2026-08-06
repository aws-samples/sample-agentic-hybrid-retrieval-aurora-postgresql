CREATE OR REPLACE VIEW proof.v_answer_receipts
WITH (security_invoker = true) AS
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
        'document_version_id', citation.document_version_id,
        'chunk_version_id', citation.chunk_version_id,
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
  ) AS citations,
  answer.validation_status
FROM proof.agent_answers answer
LEFT JOIN proof.answer_citations citation ON citation.run_id = answer.run_id
LEFT JOIN evidence.evidence_items item ON item.evidence_id = citation.evidence_id
GROUP BY answer.run_id;

-- Dropped rather than replaced: CREATE OR REPLACE VIEW can only append columns
-- to the end of the select list, and this view keeps positions next to their
-- scores. Nothing else in the schema depends on it.
DROP VIEW IF EXISTS proof.v_candidate_receipts;

CREATE VIEW proof.v_candidate_receipts
WITH (security_invoker = true) AS
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
  candidate.exact_identifier_position,
  candidate.match_tier,
  candidate.rrf_score,
  candidate.rerank_score,
  candidate.final_score,
  candidate.explanation,
  candidate.evidence_snapshot
FROM proof.retrieval_candidates candidate
JOIN evidence.evidence_items item ON item.evidence_id = candidate.evidence_id;

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

CREATE OR REPLACE FUNCTION proof.evaluate_subquestion_coverage(
  p_run_id uuid,
  p_required_kinds text[],
  p_top_n integer DEFAULT 8
)
RETURNS TABLE (
  covered boolean,
  missing_kinds text[],
  covering_evidence_ids jsonb,
  considered integer
)
LANGUAGE sql
STABLE
AS $$
WITH required AS (
  SELECT DISTINCT required_kind
  FROM unnest(p_required_kinds) AS required_kind
),
top_candidates AS MATERIALIZED (
  SELECT
    item.evidence_kind,
    item.external_key,
    candidate.result_rank
  FROM proof.retrieval_candidates candidate
  JOIN evidence.evidence_items item
    ON item.evidence_id = candidate.evidence_id
  WHERE candidate.run_id = p_run_id
  ORDER BY candidate.result_rank
  LIMIT greatest(p_top_n, 1)
),
covering AS (
  SELECT DISTINCT ON (candidate.evidence_kind)
    candidate.evidence_kind,
    candidate.external_key
  FROM top_candidates candidate
  JOIN required
    ON required.required_kind = candidate.evidence_kind
  ORDER BY candidate.evidence_kind, candidate.result_rank
),
missing AS (
  SELECT required.required_kind
  FROM required
  WHERE NOT EXISTS (
    SELECT 1
    FROM covering
    WHERE covering.evidence_kind = required.required_kind
  )
)
SELECT
  NOT EXISTS (SELECT 1 FROM missing),
  ARRAY(SELECT required_kind FROM missing ORDER BY required_kind),
  coalesce(
    (
      SELECT jsonb_object_agg(evidence_kind, external_key)
      FROM covering
    ),
    '{}'::jsonb
  ),
  (SELECT count(*)::integer FROM top_candidates)
$$;
