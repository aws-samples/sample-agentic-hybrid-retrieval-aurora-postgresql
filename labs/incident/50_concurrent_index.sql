\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 2, terminal B: CREATE INDEX CONCURRENTLY'

SET application_name = 'workbench-lab-concurrent-index';
SET statement_timeout = '10min';

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

\timing on
CREATE INDEX CONCURRENTLY idx_orders_customer_created
  ON workbench_lab.orders (customer_id, created_at DESC);
\timing off

\echo 'COMPLETE: the concurrent index build reached a valid state.'
