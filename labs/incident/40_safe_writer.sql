\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 2, terminal A: hold one normal writer transaction'

SET application_name = 'workbench-lab-safe-writer';
SET statement_timeout = '10min';
SET idle_in_transaction_session_timeout = '10min';

SELECT
  to_regclass('workbench_lab.orders') IS NOT NULL AS lab_ready,
  to_regclass(
    'workbench_lab.idx_orders_customer_created'
  ) IS NULL AS target_index_absent
\gset

\if :lab_ready
\else
  \warn 'REMEDY: run labs/incident/00_setup.sql first.'
  \quit 3
\endif

\if :target_index_absent
\else
  \warn 'REMEDY: rerun setup before the safe phase.'
  \quit 3
\endif

BEGIN;
SELECT pg_backend_pid() AS safe_writer_pid
\gset

UPDATE workbench_lab.orders
SET
  status = 'safe-writer-held',
  updated_at = clock_timestamp()
WHERE order_id = 2
RETURNING order_id, status;

\echo 'HOLDING: writer backend' :safe_writer_pid 'owns granted RowExclusiveLock.'
\echo 'Run 50_concurrent_index.sql in terminal B, then 60_observe_safe.sql in terminal C.'
\prompt 'After terminal C reports PASS, press Enter to COMMIT the writer: ' release_writer

COMMIT;
\echo 'COMMITTED: the concurrent build can now finish its safe-point wait.'
