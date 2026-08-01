\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 1, terminal B: prove reads continue and a writer waits'

SET application_name = 'workbench-lab-blocked-writer';
SET lock_timeout = '5min';
SET statement_timeout = '6min';

SELECT to_regclass('workbench_lab.orders') IS NOT NULL AS lab_ready
\gset

\if :lab_ready
\else
  \warn 'REMEDY: run labs/incident/00_setup.sql first.'
  \quit 3
\endif

SELECT pg_backend_pid() AS writer_pid;

\timing on
SELECT count(*) AS readable_rows
FROM workbench_lab.orders;

\echo 'READ PASSED: AccessShareLock is compatible with the index ShareLock.'
\echo 'The next UPDATE should wait until terminal A rolls back.'

UPDATE workbench_lab.orders
SET
  status = 'unsafe-writer-drained',
  updated_at = clock_timestamp()
WHERE order_id = 1
RETURNING order_id, status;
\timing off

\echo 'WRITER DRAINED: the UPDATE completed after the ordinary index lock released.'
