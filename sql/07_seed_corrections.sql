-- Compatibility corrections for older copies of the committed seed dump.
--
-- The live workshop path uses SQL final scoring. Earlier seed snapshots used
-- participant-visible "rerank" labels for the same canonical score values.
-- Keep the table columns for backward compatibility, but normalize the stored
-- JSON labels that the API returns.

UPDATE ops.agent_answers
SET citations = (
  SELECT jsonb_agg(
    (citation - 'rerank') ||
    jsonb_build_object(
      'score', coalesce(citation->'score', citation->'rerank'),
      'meta', replace(coalesce(citation->>'meta', ''), 'rerank', 'score')
    )
    ORDER BY coalesce((citation->>'n')::int, 0)
  )
  FROM jsonb_array_elements(citations) AS citation
)
WHERE citations::text LIKE '%rerank%';

UPDATE ops.retrieval_run_metrics
SET
  profile = replace(profile, 'hybrid-rrf-rerank-v3', 'hybrid-rrf-final-v1'),
  stage_timings = (
    SELECT jsonb_agg(
      CASE
        WHEN timing->>'stage' = 'rerank'
        THEN jsonb_set(timing, '{stage}', to_jsonb('answer assembly'::text))
        ELSE timing
      END
      ORDER BY ordinal
    )
    FROM jsonb_array_elements(stage_timings) WITH ORDINALITY AS t(timing, ordinal)
  )
WHERE profile = 'hybrid-rrf-rerank-v3'
   OR stage_timings::text LIKE '%rerank%';
