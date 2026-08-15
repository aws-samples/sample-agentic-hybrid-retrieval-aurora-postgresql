\set ON_ERROR_STOP on
\echo '== Mosaic measurement scaffolding =='
\echo 'Graded evaluation and HNSW benchmarking. Installed separately from the'
\echo 'core model so `\dt mosaic.*` during the session shows only the tables the'
\echo 'application reads, rather than empty measurement tables a participant has'
\echo 'no reason to open.'
\echo ''
\echo 'Install this when capturing Recall@10, latency, QPS, or HNSW build time.'

\ir 11_evaluation.sql
\ir 13_benchmark.sql

\echo ''
\echo 'Evaluation and benchmark schemas installed (mosaic_eval, mosaic_bench).'
\echo 'These start empty. scripts/benchmark_hnsw.py writes measured HNSW runs;'
\echo 'any number they hold must still be measured on the real cluster before use.'
