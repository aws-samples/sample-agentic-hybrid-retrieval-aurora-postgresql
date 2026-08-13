\set ON_ERROR_STOP on
\echo '== Mosaic core data model =='
\echo 'Everything a participant reads during the session. Evaluation and'
\echo 'benchmark scaffolding install separately via install_labs.sql, and the'
\echo 'HNSW indexes build separately after embeddings exist.'

\ir 00_extensions.sql
\ir 01_schemas_and_types.sql
\ir 02_reference_data.sql
\ir 03_catalog.sql
\ir 04_media.sql
\ir 05_evidence.sql
\ir 06_retrieval_projection.sql
\ir 07_indexes.sql
\ir 09_search_functions.sql
\ir 10_agent_audit.sql
\ir 12_telemetry.sql
\ir 16_seed_tool_contracts.sql

\echo ''
\echo 'Core installed. `\dt mosaic.*` now lists only tables the application reads.'
\echo 'Next: load products, CALL mosaic_search.refresh_product_documents(),'
\echo 'generate embeddings, then build the concurrent HNSW indexes separately.'
