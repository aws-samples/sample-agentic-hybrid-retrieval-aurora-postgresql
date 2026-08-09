\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS mosaic;
CREATE SCHEMA IF NOT EXISTS mosaic_search;
CREATE SCHEMA IF NOT EXISTS mosaic_eval;
CREATE SCHEMA IF NOT EXISTS mosaic_bench;
CREATE SCHEMA IF NOT EXISTS mosaic_stage;

DO $$ BEGIN
    CREATE TYPE mosaic.product_domain AS ENUM (
        'consumer_electronics',
        'running_fitness',
        'home_office'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.availability_status AS ENUM (
        'in_stock',
        'low_stock',
        'out_of_stock',
        'preorder',
        'discontinued'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.media_role AS ENUM (
        'catalog',
        'detail',
        'alternate',
        'material_closeup',
        'lifestyle',
        'family_fallback',
        'hero'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.media_tier AS ENUM (
        'flagship',
        'premium',
        'family',
        'generic'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.evidence_type AS ENUM (
        'product_spec',
        'verified_review',
        'expert_summary',
        'product_qa',
        'buying_guide',
        'benchmark'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.retrieval_channel AS ENUM (
        'fts',
        'trigram',
        'vector',
        'rrf',
        'rerank',
        'agent'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.tool_outcome AS ENUM ('success', 'denied', 'error', 'timeout');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE mosaic.benchmark_result_kind AS ENUM ('measured', 'instructor', 'projected');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE OR REPLACE FUNCTION mosaic.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END
$$;
