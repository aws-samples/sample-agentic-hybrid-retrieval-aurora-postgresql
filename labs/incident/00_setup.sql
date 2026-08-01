\set ON_ERROR_STOP on
\pset pager off
\echo 'Controlled incident setup'

SET application_name = 'workbench-lab-setup';
SET lock_timeout = '5s';

SELECT
  current_database() AS database_name,
  current_user AS database_user,
  current_setting('server_version') AS engine_version;

SELECT has_database_privilege(
  current_user,
  current_database(),
  'CREATE'
) AS can_create_lab_schema
\gset

\if :can_create_lab_schema
\else
  \warn 'REMEDY: this database role needs CREATE on the workshop database.'
  \quit 3
\endif

SELECT NOT EXISTS (
  SELECT 1
  FROM pg_stat_activity
  WHERE pid <> pg_backend_pid()
    AND datname = current_database()
    AND application_name LIKE 'workbench-lab-%'
) AS no_stale_lab_sessions
\gset

\if :no_stale_lab_sessions
\else
  \warn 'REMEDY: close the other workbench-lab-* sessions, then rerun setup.'
  \quit 3
\endif

DROP SCHEMA IF EXISTS workbench_lab CASCADE;
CREATE SCHEMA workbench_lab;

CREATE TABLE workbench_lab.orders (
  order_id bigint PRIMARY KEY,
  customer_id bigint NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);

INSERT INTO workbench_lab.orders (
  order_id,
  customer_id,
  status,
  created_at,
  updated_at
)
SELECT
  value,
  1 + (value % 5000),
  'created',
  timestamptz '2026-07-31 12:00:00+00'
    - ((value % 86400) * interval '1 second'),
  timestamptz '2026-07-31 12:00:00+00'
FROM generate_series(1, 25000) AS value;

CREATE TABLE workbench_lab.lab_state (
  scenario_key text PRIMARY KEY,
  configured_rows integer NOT NULL,
  created_by name NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO workbench_lab.lab_state (
  scenario_key,
  configured_rows,
  created_by
)
VALUES (
  'INC-2047',
  25000,
  current_user
);

ANALYZE workbench_lab.orders;

SELECT
  count(*) AS order_rows,
  pg_size_pretty(pg_total_relation_size('workbench_lab.orders')) AS relation_size,
  to_regclass('workbench_lab.idx_orders_customer_created') AS target_index
FROM workbench_lab.orders;

\echo 'READY: open three terminals and run 10_unsafe_index.sql next.'
