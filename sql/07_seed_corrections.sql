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

UPDATE ops.agent_answers
SET citations = (
  SELECT jsonb_agg(
    citation ||
    jsonb_build_object(
      'meta', replace(coalesce(citation->>'meta', ''), ' score ', ' final ')
    )
    ORDER BY coalesce((citation->>'n')::int, 0)
  )
  FROM jsonb_array_elements(citations) AS citation
)
WHERE citations::text LIKE '% score %';

-- Earlier seed snapshots described the answer plan with illustrative helper
-- names. Keep the participant-visible plan aligned with the four implemented
-- Strands tools exported by backend/app/agent.py.
UPDATE ops.agent_answers
SET answer = jsonb_set(
  answer,
  '{plan}',
  jsonb_build_array(
    jsonb_build_object(
      'num', '1',
      'fn', 'infer_sources',
      'args', '("Why did Orion slip?")',
      'desc', 'Prioritized likely source systems without dropping any of the five connected evidence domains.',
      'res', '5 systems · Jira and Slack first'
    ),
    jsonb_build_object(
      'num', '2',
      'fn', 'search_evidence',
      'args', '("orion delay root cause", systems: jira+slack+confluence, window: 60d)',
      'desc', 'Lexical, semantic, and fuzzy retrieval ran in parallel inside Aurora.',
      'res', '12 strong candidates · top: ORION-1473'
    ),
    jsonb_build_object(
      'num', '3',
      'fn', 'follow_evidence_links',
      'args', '(["ORION-1473"], max_depth: 3)',
      'desc', 'Followed stored object_links across systems to the gate check, the incident, and the fix.',
      'res', '5 linked objects · 9 edges'
    ),
    jsonb_build_object(
      'num', '4',
      'fn', 'search_evidence',
      'args', '("orion customer commitments go-live", systems: salesforce)',
      'desc', 'Ran a targeted pass for commitment language scoped to accounts referencing Orion.',
      'res', '3 candidates · 1 contractual'
    ),
    jsonb_build_object(
      'num', '5',
      'fn', 'follow_evidence_links',
      'args', '(["CASE-0012345"], max_depth: 2)',
      'desc', 'Connected the customer commitment to the release decision and blocking issue.',
      'res', '3 linked objects · 2 systems'
    ),
    jsonb_build_object(
      'num', '6',
      'fn', 'synthesize_cited_answer',
      'args', '(6 sources, style: brief)',
      'desc', 'Composed the answer; every claim bound to a citation row in Aurora.',
      'res', '9 claims · 9 citations · confidence 0.92'
    )
  ),
  true
)
WHERE question_norm = 'why did orion slip?';

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
