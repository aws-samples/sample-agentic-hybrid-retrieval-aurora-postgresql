\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 1, terminal A: ordinary CREATE INDEX'

SET application_name = 'workbench-lab-unsafe-index';
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
  \warn 'REMEDY: rerun labs/incident/00_setup.sql to reset the lab.'
  \quit 3
\endif

BEGIN;
SELECT pg_backend_pid() AS blocker_pid
\gset

CREATE INDEX idx_orders_customer_created
  ON workbench_lab.orders (customer_id, created_at DESC);

\echo 'HOLDING: backend' :blocker_pid 'retains the CREATE INDEX ShareLock.'
\echo 'Run 20_blocked_writer.sql in terminal B, then 30_observe_unsafe.sql in terminal C.'
\prompt 'After terminal C reports PASS, press Enter to ROLLBACK and release the writer: ' release_lock

ROLLBACK;

SELECT to_regclass(
  'workbench_lab.idx_orders_customer_created'
) IS NULL AS ordinary_index_removed;

\echo 'RELEASED: the ordinary index transaction rolled back.'
