\set ON_ERROR_STOP on
\echo '== Mosaic snapshot upgrade =='
\echo 'Retiring unused schema objects before replaying the current core model.'

DROP VIEW IF EXISTS mosaic.v_premium_shop;
DROP VIEW IF EXISTS mosaic.v_flagship_product;
DROP VIEW IF EXISTS mosaic.v_shop_product;
DROP VIEW IF EXISTS mosaic_search.v_embedding_backlog;
DROP VIEW IF EXISTS mosaic.v_media_coverage;
DROP TABLE IF EXISTS mosaic.attribute_definition;
DROP TABLE IF EXISTS mosaic_search.synonym_rule;

\echo 'Replaying the current idempotent core model and retrieval functions.'

\ir install.sql

\echo 'Snapshot core replay complete. The Make target now applies and verifies'
\echo 'database-level pg_trgm defaults from db/config/retrieval.yaml.'
