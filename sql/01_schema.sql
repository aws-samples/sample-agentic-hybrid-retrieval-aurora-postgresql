\set ON_ERROR_STOP on

-- DEPRECATED: the `catalog.*` tree. The application does not read this schema;
-- `service/retrieval.py` queries `mosaic` and `mosaic_search` (see db/sql/).
-- Deleted by Phase 2 Unit E. See docs/rewrite-losses.md for what the rewrite
-- dropped and docs/superpowers/specs/ for the Phase 2 design.
-- Do not add features here. Do not point a lab at it.

CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS catalog_stage;
CREATE SCHEMA IF NOT EXISTS catalog_eval;

CREATE TABLE IF NOT EXISTS catalog.product (
    product_id              bigint PRIMARY KEY,
    product_uid             uuid NOT NULL UNIQUE,
    sku                     text NOT NULL UNIQUE,
    domain                  text NOT NULL,
    category                text NOT NULL,
    subcategory             text NOT NULL,
    brand                   text NOT NULL,
    model                   text NOT NULL,
    title                   text NOT NULL,
    short_description       text NOT NULL,
    long_description        text NOT NULL,
    price_usd               numeric(12,2) NOT NULL CHECK (price_usd >= 0),
    list_price_usd          numeric(12,2) NOT NULL CHECK (list_price_usd >= price_usd),
    currency                char(3) NOT NULL DEFAULT 'USD',
    rating                  numeric(2,1) NOT NULL CHECK (rating BETWEEN 0 AND 5),
    review_count            integer NOT NULL CHECK (review_count >= 0),
    availability            text NOT NULL CHECK (
        availability IN ('In Stock', 'Low Stock', 'Out of Stock')
    ),
    inventory_count         integer NOT NULL CHECK (inventory_count >= 0),
    seller_count            smallint NOT NULL CHECK (seller_count >= 0),
    shipping_days           smallint NOT NULL CHECK (shipping_days >= 0),
    warranty_months         smallint NOT NULL CHECK (warranty_months >= 0),
    return_rate             real NOT NULL CHECK (return_rate BETWEEN 0 AND 1),
    popularity_score        real NOT NULL CHECK (popularity_score BETWEEN 0 AND 1),
    quality_score           real NOT NULL CHECK (quality_score BETWEEN 0 AND 1),
    freshness_score         real NOT NULL CHECK (freshness_score BETWEEN 0 AND 1),
    metadata_completeness   real NOT NULL CHECK (metadata_completeness BETWEEN 0 AND 1),
    launch_date             date NOT NULL,
    updated_at              timestamptz NOT NULL,
    source_system           text NOT NULL,
    language                text NOT NULL DEFAULT 'en-US',
    is_refurbished          boolean NOT NULL DEFAULT false,
    is_sponsored            boolean NOT NULL DEFAULT false,
    attributes              jsonb NOT NULL DEFAULT '{}'::jsonb,
    tags                    jsonb NOT NULL DEFAULT '[]'::jsonb,
    aliases                 jsonb NOT NULL DEFAULT '[]'::jsonb,
    challenge_cohorts       jsonb NOT NULL DEFAULT '[]'::jsonb,
    canonical_group_id      text NOT NULL,
    image_key               text,
    search_text             text NOT NULL,
    embedding_text          text NOT NULL,
    trigram_text            text NOT NULL,
    search_document         tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(
            to_tsvector(
                'english',
                coalesce(brand, '') || ' ' ||
                coalesce(model, '') || ' ' ||
                coalesce(subcategory, '')
            ),
            'A'
        ) ||
        setweight(to_tsvector('english', coalesce(short_description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(search_text, '')), 'C')
    ) STORED,
    embedding               vector(1024),
    embedding_model_id      text,
    embedding_content_hash  text,
    embedded_at             timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN catalog.product.embedding IS
'Generated from embedding_text by the configured Bedrock embedding model.';
COMMENT ON COLUMN catalog.product.embedding_model_id IS
'Exact model ID used for the stored vector; query vectors must use the same model.';

CREATE TABLE IF NOT EXISTS catalog.product_media (
    product_id      bigint NOT NULL REFERENCES catalog.product(product_id) ON DELETE CASCADE,
    role            text NOT NULL DEFAULT 'primary',
    sort_order      smallint NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    image_url       text NOT NULL,
    image_source    text NOT NULL,
    image_key       text,
    alt_text        text NOT NULL DEFAULT '',
    asset_sha256    text,
    publication_status text NOT NULL DEFAULT 'review_required' CHECK (
        publication_status IN ('approved', 'review_required', 'blocked')
    ),
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, role, sort_order)
);

CREATE TABLE IF NOT EXISTS catalog.product_review (
    review_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id         bigint NOT NULL REFERENCES catalog.product(product_id) ON DELETE CASCADE,
    rating             smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title              text,
    body               text NOT NULL,
    verified_purchase  boolean NOT NULL DEFAULT false,
    helpful_votes      integer NOT NULL DEFAULT 0,
    review_date        date NOT NULL,
    sentiment_score    real CHECK (sentiment_score BETWEEN -1 AND 1),
    source_uri         text GENERATED ALWAYS AS (
        'catalog://review/' || review_id::text
    ) STORED,
    embedding          vector(1024),
    embedding_model_id text,
    embedded_at        timestamptz
);

CREATE TABLE IF NOT EXISTS catalog.retrieval_run (
    run_id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at          timestamptz,
    query_text            text NOT NULL,
    normalized_query      text NOT NULL,
    filters               jsonb NOT NULL DEFAULT '{}'::jsonb,
    strategy              text NOT NULL,
    embedding_model_id    text NOT NULL,
    rerank_model_id       text,
    rrf_k                 integer NOT NULL,
    arm_weights           jsonb NOT NULL,
    candidate_counts      jsonb NOT NULL DEFAULT '{}'::jsonb,
    stage_timings_ms      jsonb NOT NULL DEFAULT '{}'::jsonb,
    total_latency_ms      integer,
    result_product_ids    bigint[] NOT NULL DEFAULT '{}',
    diagnostics           jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS catalog.retrieval_candidate (
    run_id                 uuid NOT NULL REFERENCES catalog.retrieval_run(run_id) ON DELETE CASCADE,
    product_id             bigint NOT NULL REFERENCES catalog.product(product_id),
    lexical_rank           integer,
    lexical_score          real,
    lexical_contribution   double precision,
    trigram_rank           integer,
    trigram_score          real,
    trigram_contribution   double precision,
    semantic_rank          integer,
    semantic_score         real,
    semantic_contribution  double precision,
    rrf_score              double precision NOT NULL,
    pre_rerank_rank        integer NOT NULL,
    rerank_score           real,
    final_rank             integer,
    business_score         real NOT NULL,
    hard_filter_pass       boolean NOT NULL DEFAULT true,
    PRIMARY KEY (run_id, product_id)
);

CREATE TABLE IF NOT EXISTS catalog.agent_run (
    agent_run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at          timestamptz,
    question              text NOT NULL,
    plan                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieval_run_ids     uuid[] NOT NULL DEFAULT '{}',
    answer                text,
    model_id              text,
    tool_trace            jsonb NOT NULL DEFAULT '[]'::jsonb,
    usage                 jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS catalog.agent_citation (
    agent_run_id      uuid NOT NULL REFERENCES catalog.agent_run(agent_run_id) ON DELETE CASCADE,
    citation_number   integer NOT NULL CHECK (citation_number > 0),
    product_id        bigint NOT NULL REFERENCES catalog.product(product_id),
    review_id         bigint REFERENCES catalog.product_review(review_id),
    source_uri        text NOT NULL,
    source_revision   text NOT NULL,
    quote             text NOT NULL,
    PRIMARY KEY (agent_run_id, citation_number)
);

CREATE TABLE IF NOT EXISTS catalog_stage.product_raw (
    product_id text, product_uid text, sku text, domain text, category text, subcategory text,
    brand text, model text, title text, short_description text, long_description text,
    price_usd text, list_price_usd text, currency text, rating text, review_count text,
    availability text, inventory_count text, seller_count text, shipping_days text,
    warranty_months text, return_rate text, popularity_score text, quality_score text,
    freshness_score text, metadata_completeness text, launch_date text, updated_at text,
    source_system text, language text, is_refurbished text, is_sponsored text,
    attributes_json text, tags_json text, aliases_json text, search_text text,
    embedding_text text, challenge_cohorts_json text, canonical_group_id text, image_key text
);

CREATE TABLE IF NOT EXISTS catalog_stage.product_media_raw (
    product_id text,
    role text,
    sort_order text,
    image_url text,
    image_source text,
    image_key text,
    alt_text text,
    asset_sha256 text,
    publication_status text
);

CREATE TABLE IF NOT EXISTS catalog_eval.query (
    query_id             text PRIMARY KEY,
    query_text           text NOT NULL,
    domain               text,
    intent               text,
    filters              jsonb NOT NULL DEFAULT '{}'::jsonb,
    expected_techniques  jsonb NOT NULL DEFAULT '[]'::jsonb,
    target_product_id    bigint,
    notes                text
);

CREATE TABLE IF NOT EXISTS catalog_eval.judgment (
    query_id          text NOT NULL REFERENCES catalog_eval.query(query_id) ON DELETE CASCADE,
    product_id        bigint NOT NULL REFERENCES catalog.product(product_id) ON DELETE CASCADE,
    relevance_grade   smallint NOT NULL CHECK (relevance_grade BETWEEN 0 AND 3),
    reason            text,
    PRIMARY KEY (query_id, product_id)
);
