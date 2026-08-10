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

-- One run of the unweighted/weighted fusion comparison.
--
-- Phase 4's `rrf_recomputes` assertion re-derives a fused order from stored arm
-- ranks and stored fusion inputs, then checks the persisted order matches. That
-- assertion needs no schema change when it lands: everything it reads is here.
-- Unit D ships the substrate, not the assertion.
--
-- `weights` and `rrf_k` are stored per run rather than read from the yaml at
-- assertion time, because the yaml is editable and a recompute must use the
-- inputs the run actually used. A recompute against today's config would pass or
-- fail for the wrong reason.
CREATE TABLE IF NOT EXISTS mosaic.fusion_comparison (
    fusion_comparison_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at           timestamptz NOT NULL DEFAULT now(),
    search_event_id       uuid REFERENCES mosaic.search_event(search_event_id) ON DELETE SET NULL,
    query_text            text NOT NULL,
    normalized_query      text,
    filters               jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Arm caps and the fusion inputs both functions received. Identical by
    -- construction; stored so that claim is checkable after the fact.
    retrieval_profile     jsonb NOT NULL DEFAULT '{}'::jsonb,
    rrf_k                 integer NOT NULL CHECK (rrf_k > 0),
    weights               jsonb NOT NULL,
    -- The substrate assertion's verdict, per call. False must be impossible by
    -- construction; it is recorded rather than assumed so a regression is
    -- visible in the data and not only in a failed request.
    candidate_sets_identical boolean NOT NULL,
    candidate_count       integer NOT NULL CHECK (candidate_count >= 0),
    -- Both final orders, as product_id arrays in rank order.
    unweighted_order      bigint[] NOT NULL,
    weighted_order        bigint[] NOT NULL,
    orders_differ         boolean NOT NULL,
    unweighted_latency_ms integer CHECK (unweighted_latency_ms >= 0),
    weighted_latency_ms   integer CHECK (weighted_latency_ms >= 0)
);

-- Per-candidate detail for one comparison: all three arm ranks, both fused
-- scores, and both fused positions. One row per product per comparison.
CREATE TABLE IF NOT EXISTS mosaic.fusion_comparison_candidate (
    fusion_comparison_id  uuid NOT NULL
        REFERENCES mosaic.fusion_comparison(fusion_comparison_id) ON DELETE CASCADE,
    product_id            bigint NOT NULL REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    -- Arm ranks. NULL means the arm did not return this candidate, which is a
    -- fact about the arm and not a missing value.
    fts_rank              integer,
    trigram_rank          integer,
    semantic_rank         integer,
    unweighted_rrf_score  double precision NOT NULL,
    weighted_rrf_score    double precision NOT NULL,
    unweighted_rank       integer NOT NULL CHECK (unweighted_rank > 0),
    weighted_rank         integer NOT NULL CHECK (weighted_rank > 0),
    rank_delta            integer NOT NULL,
    provenance            jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (fusion_comparison_id, product_id)
);

CREATE INDEX IF NOT EXISTS fusion_comparison_occurred_idx
    ON mosaic.fusion_comparison (occurred_at DESC);
CREATE INDEX IF NOT EXISTS fusion_comparison_candidate_weighted_idx
    ON mosaic.fusion_comparison_candidate (fusion_comparison_id, weighted_rank);
CREATE INDEX IF NOT EXISTS fusion_comparison_candidate_moved_idx
    ON mosaic.fusion_comparison_candidate (fusion_comparison_id, rank_delta)
    WHERE rank_delta <> 0;
