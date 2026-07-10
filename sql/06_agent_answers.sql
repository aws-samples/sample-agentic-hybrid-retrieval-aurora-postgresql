-- Canonical, cited agent answers and per-run diagnostics metrics.
--
-- These tables let the API serve the exact Orion narrative (and the exact
-- diagnostics numbers) from real rows in Aurora rather than from hardcoded
-- strings in the UI. The seed (seed/generate.py) populates them; the API reads
-- them back. Adding them is additive and idempotent.

CREATE TABLE IF NOT EXISTS ops.agent_answers (
  answer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES ops.retrieval_runs(run_id) ON DELETE SET NULL,
  question text NOT NULL,
  question_norm text NOT NULL,
  -- Structured answer body (lead, sections, pull quote, commit table, plan)
  -- as authored for the mockups. Rendered verbatim by the UI.
  answer jsonb NOT NULL,
  confidence numeric NOT NULL DEFAULT 0.0,
  source_count int NOT NULL DEFAULT 0,
  system_count int NOT NULL DEFAULT 0,
  -- Ordered citations: [{n, source_system, external_id, title, url, score, meta, why}]
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(question_norm)
);

-- One row per retrieval run holding the funnel + stage-timing numbers the
-- diagnostics view renders (fetched/deduped/fused/above-cut/cited, ms/stage).
CREATE TABLE IF NOT EXISTS ops.retrieval_run_metrics (
  run_id uuid PRIMARY KEY REFERENCES ops.retrieval_runs(run_id) ON DELETE CASCADE,
  profile text NOT NULL,
  embedding_model text NOT NULL,
  embedding_dim int NOT NULL DEFAULT 1024,
  index_spec text NOT NULL,
  fired_at timestamptz NOT NULL,
  total_latency_ms int NOT NULL,
  p50_latency_ms int NOT NULL,
  rrf_k int NOT NULL DEFAULT 60,
  ranker_weights numeric[] NOT NULL DEFAULT '{1,1,0.5}',
  rerank_cut numeric NOT NULL DEFAULT 0.55,
  reranked_count int NOT NULL DEFAULT 0,
  -- funnel: {fetched, deduped, fused, above_cut, cited}
  funnel jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- stage_timings: [{stage, ms}]
  stage_timings jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_answers_question_norm ON ops.agent_answers(question_norm);
