\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 2, terminal C: prove compatible locks and live DML'

SET application_name = 'workbench-lab-observer-safe';
SET lock_timeout = '5s';
SET statement_timeout = '30s';

DO $$
DECLARE
  deadline timestamptz := clock_timestamp() + interval '15 seconds';
BEGIN
  LOOP
    EXIT WHEN EXISTS (
      SELECT 1
      FROM pg_stat_activity activity
      JOIN pg_locks lock_row ON lock_row.pid = activity.pid
      WHERE activity.application_name = 'workbench-lab-concurrent-index'
        AND lock_row.relation = 'workbench_lab.orders'::regclass
        AND lock_row.mode = 'ShareUpdateExclusiveLock'
        AND lock_row.granted
    );
    IF clock_timestamp() >= deadline THEN
      RAISE EXCEPTION
        'concurrent index lock not observed; start terminals A and B first';
    END IF;
    PERFORM pg_sleep(0.1);
  END LOOP;
END
$$;

SELECT
  activity.pid,
  activity.application_name,
  activity.state,
  activity.wait_event_type,
  activity.wait_event,
  lock_row.mode,
  lock_row.granted
FROM pg_stat_activity activity
JOIN pg_locks lock_row ON lock_row.pid = activity.pid
WHERE lock_row.relation = 'workbench_lab.orders'::regclass
  AND activity.application_name IN (
    'workbench-lab-safe-writer',
    'workbench-lab-concurrent-index'
  )
ORDER BY activity.application_name, lock_row.mode;

WITH concurrent_build AS (
  SELECT pid
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-concurrent-index'
),
safe_writer AS (
  SELECT pid, wait_event_type, wait_event
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-safe-writer'
)
SELECT
  EXISTS (
    SELECT 1
    FROM concurrent_build
    JOIN pg_locks lock_row ON lock_row.pid = concurrent_build.pid
    WHERE lock_row.relation = 'workbench_lab.orders'::regclass
      AND lock_row.mode = 'ShareUpdateExclusiveLock'
      AND lock_row.granted
  )
  AND EXISTS (
    SELECT 1
    FROM safe_writer
    JOIN pg_locks lock_row ON lock_row.pid = safe_writer.pid
    WHERE lock_row.relation = 'workbench_lab.orders'::regclass
      AND lock_row.mode = 'RowExclusiveLock'
      AND lock_row.granted
      AND NOT (
        safe_writer.wait_event_type = 'Lock'
        AND lower(coalesce(safe_writer.wait_event, '')) = 'relation'
      )
  ) AS compatible_locks_visible
\gset

\if :compatible_locks_visible
\else
  \warn 'FAIL: expected compatible relation locks were not both visible.'
  \quit 3
\endif

\echo 'The concurrent build may wait on virtualxid; the fresh UPDATE must not wait on its relation lock.'
\timing on
UPDATE workbench_lab.orders
SET
  status = 'safe-probe',
  updated_at = clock_timestamp()
WHERE order_id = 3
RETURNING order_id, status;
\timing off

SELECT status = 'safe-probe' AS fresh_write_completed
FROM workbench_lab.orders
WHERE order_id = 3
\gset

\if :fresh_write_completed
  \echo 'PASS: RowExclusiveLock coexisted with ShareUpdateExclusiveLock and fresh DML completed.'
\else
  \warn 'FAIL: the fresh writer did not commit its expected row.'
  \quit 3
\endif

\echo 'Return to terminal A and press Enter so the concurrent build can finish.'
