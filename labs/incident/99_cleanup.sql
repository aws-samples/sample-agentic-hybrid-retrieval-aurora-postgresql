\set ON_ERROR_STOP on
\pset pager off
\echo 'Controlled incident cleanup'

SET application_name = 'workbench-lab-cleanup';
SET lock_timeout = '5s';

SELECT NOT EXISTS (
  SELECT 1
  FROM pg_stat_activity
  WHERE pid <> pg_backend_pid()
    AND application_name LIKE 'workbench-lab-%'
) AS no_active_lab_sessions
\gset

\if :no_active_lab_sessions
\else
  \warn 'REMEDY: close the other workbench-lab-* terminals before cleanup.'
  \quit 3
\endif

DROP SCHEMA IF EXISTS workbench_lab CASCADE;

\echo 'CLEAN: workbench_lab was removed.'
\echo 'The measured data/generated/incident-lab/lock_capture.json file was retained.'
