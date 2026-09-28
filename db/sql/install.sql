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
\ir 08_search_channels.sql
-- The two lab exercise files. Lab 2's contribution comes first because Lab 1's
-- hybrid search, the weighted fusion and the evidence search all call it.
\ir ../../labs/lab2_rank/rrf_contribution.sql
\ir ../../labs/lab1_retrieve/hybrid_search.sql
\ir 09_weighted_fusion.sql
\ir 10_evidence_search.sql
\ir 11_query_coverage.sql
\ir 12_agent_audit.sql
\ir 13_telemetry.sql
\ir 14_seed_tool_contracts.sql

\echo ''
\echo 'Core installed. `\dt mosaic.*` now lists only tables the application reads.'
\echo 'Next: load products, CALL mosaic_search.refresh_product_documents(),'
\echo 'generate embeddings, then build the concurrent HNSW indexes separately.'
