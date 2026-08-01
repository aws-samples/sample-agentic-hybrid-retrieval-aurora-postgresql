\set ON_ERROR_STOP on
\pset pager off
\echo 'Final verification'

SET application_name = 'workbench-lab-verify';
SET lock_timeout = '5s';

SELECT
  index_state.indisready
  AND index_state.indisvalid
  AND index_state.indislive AS concurrent_index_valid
FROM pg_index index_state
WHERE index_state.indexrelid =
  'workbench_lab.idx_orders_customer_created'::regclass
\gset

\if :concurrent_index_valid
\else
  \warn 'FAIL: the concurrent index is not ready, valid, and live.'
  \quit 3
\endif

SELECT order_id, status, updated_at
FROM workbench_lab.orders
WHERE order_id IN (1, 2, 3)
ORDER BY order_id;

SELECT NOT EXISTS (
  SELECT 1
  FROM pg_locks
  WHERE relation = 'workbench_lab.orders'::regclass
    AND NOT granted
) AS no_waiting_relation_locks
\gset

\if :no_waiting_relation_locks
\else
  \warn 'FAIL: an ungranted relation lock remains on the lab table.'
  \quit 3
\endif

EXPLAIN (COSTS OFF)
SELECT order_id, customer_id, created_at
FROM workbench_lab.orders
WHERE customer_id = 42
ORDER BY created_at DESC
LIMIT 10;

\echo 'PASS: safe index is ready, valid, live, and no relation waiters remain.'
