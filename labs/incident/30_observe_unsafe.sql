\set ON_ERROR_STOP on
\pset pager off
\echo 'Phase 1, terminal C: inspect the live lock chain'

SET application_name = 'workbench-lab-observer-unsafe';
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
      WHERE activity.application_name = 'workbench-lab-blocked-writer'
        AND activity.state = 'active'
        AND activity.wait_event_type = 'Lock'
        AND lower(activity.wait_event) = 'relation'
        AND lock_row.relation = 'workbench_lab.orders'::regclass
        AND lock_row.mode = 'RowExclusiveLock'
        AND NOT lock_row.granted
    );
    IF clock_timestamp() >= deadline THEN
      RAISE EXCEPTION
        'writer did not enter Lock:relation wait; start terminals A and B first';
    END IF;
    PERFORM pg_sleep(0.1);
  END LOOP;
END
$$;

\timing on
SELECT count(*) AS readable_rows
FROM workbench_lab.orders;
\timing off

SELECT
  activity.pid,
  activity.application_name,
  activity.state,
  activity.wait_event_type,
  activity.wait_event,
  left(regexp_replace(activity.query, '\s+', ' ', 'g'), 100) AS statement
FROM pg_stat_activity activity
WHERE activity.application_name IN (
  'workbench-lab-unsafe-index',
  'workbench-lab-blocked-writer'
)
ORDER BY activity.application_name;

SELECT
  activity.pid,
  activity.application_name,
  lock_row.mode,
  lock_row.granted,
  lock_row.fastpath,
  lock_row.waitstart
FROM pg_locks lock_row
JOIN pg_stat_activity activity ON activity.pid = lock_row.pid
WHERE lock_row.relation = 'workbench_lab.orders'::regclass
  AND activity.application_name IN (
    'workbench-lab-unsafe-index',
    'workbench-lab-blocked-writer'
  )
ORDER BY activity.application_name, lock_row.granted DESC, lock_row.mode;

SELECT
  writer.pid AS blocked_pid,
  pg_blocking_pids(writer.pid) AS blocking_pids
FROM pg_stat_activity writer
WHERE writer.application_name = 'workbench-lab-blocked-writer';

WITH blocker AS (
  SELECT pid
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-unsafe-index'
),
writer AS (
  SELECT pid, state, wait_event_type, wait_event
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-blocked-writer'
)
SELECT
  (SELECT count(*) FROM workbench_lab.orders) = 25000
  AND EXISTS (
    SELECT 1
    FROM blocker
    JOIN pg_locks lock_row ON lock_row.pid = blocker.pid
    WHERE lock_row.relation = 'workbench_lab.orders'::regclass
      AND lock_row.mode = 'ShareLock'
      AND lock_row.granted
  )
  AND EXISTS (
    SELECT 1
    FROM writer
    JOIN pg_locks lock_row ON lock_row.pid = writer.pid
    WHERE writer.state = 'active'
      AND writer.wait_event_type = 'Lock'
      AND lower(writer.wait_event) = 'relation'
      AND lock_row.relation = 'workbench_lab.orders'::regclass
      AND lock_row.mode = 'RowExclusiveLock'
      AND NOT lock_row.granted
  )
  AND EXISTS (
    SELECT 1
    FROM blocker
    CROSS JOIN writer
    WHERE blocker.pid = ANY(pg_blocking_pids(writer.pid))
  ) AS unsafe_checks_pass
\gset

\if :unsafe_checks_pass
  \echo 'PASS: reads continued; ShareLock blocked the writer RowExclusiveLock.'
\else
  \warn 'FAIL: the observed lock chain did not match the incident contract.'
  \quit 3
\endif

\if :{?capture_file}
\else
  \set capture_file 'data/generated/incident-lab/lock_capture.json'
\endif

\! mkdir -p data/generated/incident-lab
\pset format unaligned
\pset tuples_only on
\o :capture_file
WITH blocker AS (
  SELECT
    pid,
    state,
    xact_start,
    query_start,
    query
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-unsafe-index'
),
writer AS (
  SELECT
    pid,
    state,
    wait_event_type,
    wait_event,
    xact_start,
    query_start,
    query
  FROM pg_stat_activity
  WHERE application_name = 'workbench-lab-blocked-writer'
),
blocker_lock AS (
  SELECT mode, granted, fastpath
  FROM pg_locks
  CROSS JOIN blocker
  WHERE pg_locks.pid = blocker.pid
    AND pg_locks.relation = 'workbench_lab.orders'::regclass
    AND pg_locks.mode = 'ShareLock'
),
writer_lock AS (
  SELECT mode, granted, fastpath, waitstart
  FROM pg_locks
  CROSS JOIN writer
  WHERE pg_locks.pid = writer.pid
    AND pg_locks.relation = 'workbench_lab.orders'::regclass
    AND pg_locks.mode = 'RowExclusiveLock'
)
SELECT jsonb_pretty(
  jsonb_build_object(
    'source_uri', 'workshop://live/incident-lab/LOCK-LIVE-001',
    'observation_window', jsonb_build_object(
      'start', least(blocker.xact_start, writer.xact_start),
      'end', clock_timestamp()
    ),
    'external_key', 'LOCK-LIVE-001',
    'title', 'Participant-captured checkout writer blocked by ordinary index build',
    'occurred_at', clock_timestamp(),
    'available_at', clock_timestamp(),
    'acl', jsonb_build_object('visibility', 'workshop'),
    'body', format(
      'Plain CREATE INDEX held granted ShareLock on workbench_lab.orders; writer PID %s waited for RowExclusiveLock while reads continued.',
      writer.pid
    ),
    'structured', jsonb_build_object(
      'incident_external_key', 'INC-2047',
      'change_external_key', 'CHG-1842',
      'captured_at', clock_timestamp(),
      'relation_name', 'workbench_lab.orders',
      'relation_oid', 'workbench_lab.orders'::regclass::oid,
      'blocked_pid', writer.pid,
      'blocking_pid', blocker.pid,
      'blocked_state', writer.state,
      'blocked_query_start', writer.query_start,
      'wait_event_type', writer.wait_event_type,
      'wait_event', writer.wait_event,
      'blocked_lock_mode', writer_lock.mode,
      'blocked_lock_granted', writer_lock.granted,
      'blocking_lock_mode', blocker_lock.mode,
      'blocking_lock_granted', blocker_lock.granted,
      'blocking_pids', to_jsonb(pg_blocking_pids(writer.pid)),
      'blocking_pids_sql', format(
        'SELECT pg_blocking_pids(%s);',
        writer.pid
      ),
      'blocking_pids_output', pg_blocking_pids(writer.pid)::text,
      'blocked_statement', writer.query,
      'blocking_statement', blocker.query,
      'raw_capture', jsonb_build_object(
        'blocker', to_jsonb(blocker),
        'writer', to_jsonb(writer),
        'blocker_lock', to_jsonb(blocker_lock),
        'writer_lock', to_jsonb(writer_lock)
      )
    ),
    'links', jsonb_build_array(
      jsonb_build_object(
        'to_external_key', 'CHG-1842',
        'to_kind', 'change',
        'relation', 'evidence_supports',
        'confidence', 1.0
      )
    )
  )
)
FROM blocker
CROSS JOIN writer
CROSS JOIN blocker_lock
CROSS JOIN writer_lock;
\o
\pset tuples_only off
\pset format aligned

\echo 'CAPTURED:' :capture_file
\echo 'Return to terminal A and press Enter to release the blocked writer.'
