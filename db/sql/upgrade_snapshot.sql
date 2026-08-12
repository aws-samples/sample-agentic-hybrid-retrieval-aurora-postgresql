\set ON_ERROR_STOP on
\echo '== Mosaic snapshot upgrade =='
\echo 'Replaying the current idempotent core model and retrieval functions.'

\ir install.sql

\echo 'Snapshot core replay complete. The Make target now applies and verifies'
\echo 'database-level pg_trgm defaults from db/config/retrieval.yaml.'
