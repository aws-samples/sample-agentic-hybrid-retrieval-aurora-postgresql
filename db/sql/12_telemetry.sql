\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS mosaic.search_event (
    search_event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at            timestamptz NOT NULL DEFAULT now(),
    session_id             text,
    agent_turn_id          uuid REFERENCES mosaic.agent_turn(agent_turn_id),
    query_text             text NOT NULL,
    normalized_query       text,
    filters                jsonb NOT NULL DEFAULT '{}'::jsonb,
    retrieval_profile      jsonb NOT NULL DEFAULT '{}'::jsonb,
    candidate_counts       jsonb NOT NULL DEFAULT '{}'::jsonb,
    total_latency_ms       integer CHECK (total_latency_ms >= 0),
    plan_json              jsonb,
    diagnostics            jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE mosaic.agent_tool_event
    DROP CONSTRAINT IF EXISTS agent_tool_event_search_event_id_fkey;
ALTER TABLE mosaic.agent_tool_event
    ADD CONSTRAINT agent_tool_event_search_event_id_fkey
    FOREIGN KEY (search_event_id) REFERENCES mosaic.search_event(search_event_id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS mosaic.search_result_event (
    search_event_id       uuid NOT NULL REFERENCES mosaic.search_event(search_event_id) ON DELETE CASCADE,
    product_id            bigint NOT NULL REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    result_rank           integer NOT NULL CHECK (result_rank > 0),
    fts_rank              integer,
    trigram_rank          integer,
    semantic_rank         integer,
    fused_rank            integer,
    rerank_rank           integer,
    scores                jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance            jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (search_event_id, product_id)
);

CREATE INDEX IF NOT EXISTS search_event_occurred_brin_idx
    ON mosaic.search_event USING brin (occurred_at);
CREATE INDEX IF NOT EXISTS search_event_session_idx
    ON mosaic.search_event (session_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS search_result_rank_idx
    ON mosaic.search_result_event (search_event_id, result_rank);
