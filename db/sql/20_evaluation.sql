\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS mosaic_eval.query (
    query_id              text PRIMARY KEY,
    query_text            text NOT NULL,
    domain                mosaic.product_domain,
    intent                text,
    filters               jsonb NOT NULL DEFAULT '{}'::jsonb,
    expected_techniques   mosaic.retrieval_channel[] NOT NULL DEFAULT ARRAY[]::mosaic.retrieval_channel[],
    target_product_id     bigint REFERENCES mosaic.product(product_id),
    is_demo_query         boolean NOT NULL DEFAULT false,
    notes                 text,
    metadata              jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS mosaic_eval.judgment (
    query_id            text NOT NULL REFERENCES mosaic_eval.query(query_id) ON DELETE CASCADE,
    product_id          bigint NOT NULL REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    relevance_grade     smallint NOT NULL CHECK (relevance_grade BETWEEN 0 AND 3),
    reason              text,
    judged_by           text NOT NULL DEFAULT 'synthetic_ground_truth',
    PRIMARY KEY (query_id, product_id)
);

CREATE TABLE IF NOT EXISTS mosaic_eval.run (
    eval_run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name             text NOT NULL,
    retrieval_profile    jsonb NOT NULL,
    embedding_model_key  text REFERENCES mosaic.embedding_model(model_key),
    reranker_model       text,
    git_commit           text,
    dataset_manifest     text,
    started_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz,
    metadata             jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS mosaic_eval.result (
    eval_run_id          uuid NOT NULL REFERENCES mosaic_eval.run(eval_run_id) ON DELETE CASCADE,
    query_id             text NOT NULL REFERENCES mosaic_eval.query(query_id) ON DELETE CASCADE,
    product_id           bigint NOT NULL REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    result_rank          integer NOT NULL CHECK (result_rank > 0),
    fts_score            real,
    trigram_score        real,
    semantic_score       real,
    rrf_score            double precision,
    rerank_score         real,
    final_score          double precision,
    latency_ms           integer CHECK (latency_ms >= 0),
    provenance           jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (eval_run_id, query_id, product_id)
);

CREATE TABLE IF NOT EXISTS mosaic_eval.metric (
    eval_run_id       uuid NOT NULL REFERENCES mosaic_eval.run(eval_run_id) ON DELETE CASCADE,
    metric_name       text NOT NULL,
    metric_value      double precision NOT NULL,
    scope             jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (eval_run_id, metric_name, scope)
);

CREATE INDEX IF NOT EXISTS eval_result_query_rank_idx
    ON mosaic_eval.result (eval_run_id, query_id, result_rank);
CREATE INDEX IF NOT EXISTS eval_judgment_product_idx
    ON mosaic_eval.judgment (product_id, relevance_grade DESC);
