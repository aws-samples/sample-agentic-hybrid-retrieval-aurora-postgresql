\set ON_ERROR_STOP on
CREATE SCHEMA IF NOT EXISTS catalog_bench;

-- Render this file with scripts/render_sql.py when using another dimension.
CREATE TABLE IF NOT EXISTS catalog_bench.vector_item (
    item_id bigint PRIMARY KEY,
    cluster_id integer NOT NULL,
    domain_id smallint NOT NULL,
    price_bucket smallint NOT NULL,
    embedding vector(1024) NOT NULL
);

CREATE INDEX IF NOT EXISTS vector_item_filter_idx
ON catalog_bench.vector_item(domain_id, price_bucket);
