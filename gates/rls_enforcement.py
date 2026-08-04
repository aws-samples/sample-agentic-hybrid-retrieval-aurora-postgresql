#!/usr/bin/env python3
"""G-27 - RLS enforcement assertion (D24, A1/A2/A7/A8).

Four groups, in the order a reader should trust them, preceded by a precondition
that has to come first:

(0) the capture can prove something. Restricted rows exist in
    ``casework.evidence_items`` AND survived into both derived tables, measured on
    the engine rather than hand-typed. This is not bookkeeping: (b) below asserts
    that ``persona_app_engineer`` sees zero restricted rows, which is trivially true
    of an empty set. The owner's own RLS exposure is measured alongside it, because
    the owner writes every derived evidence row and a filtered owner truncates them
    while reporting success. A gate that goes green over an empty enforcement claim
    is worse than one that goes red.

(a) fail-closed. Connected as ``workshop_app`` with **no role set**, a SELECT on
    each of the three read-path tables raises ``permission denied``. An error is
    strictly stronger than "returns zero rows": it proves the pool identity has no
    standing privilege path at all, so a forgotten ``SET ROLE`` cannot leak.

(b) row filtering. Under ``SET LOCAL ROLE persona_app_engineer`` every restricted
    row returns zero rows at each of ``casework.evidence_items``,
    ``retrieval.documents`` and ``retrieval.chunks`` - the raw tables, no arm, no
    application predicate. Under ``persona_dba`` the same rows are present. Both
    retrieval tables matter: ``vector_search`` reads ``retrieval.chunks``
    standalone and ``fuzzy_search`` reads ``retrieval.documents`` standalone, so a
    policy on ``casework.evidence_items`` alone would leak restricted chunk text
    while headers stayed filtered.

(b') the same filtering at every other reachable table, discovered from the
    catalog. Section 2 of sql/11_roles_rls.sql grants each persona SELECT ON ALL
    TABLES IN SCHEMA casework, retrieval and proof, so the bypass class is "any
    table reachable by a schema-wide grant is a door". The tables are therefore
    enumerated by asking the engine which ones carry an evidence, capture, run or
    acl reference - not by a hand-typed list, which goes stale the first time a
    capture adds a table.

    Three mechanisms, routed by which one the DDL uses and asserted separately
    because they fail differently and share only the app-engineer half:

    (b')  evidence-keyed tables clear through casework.evidence_items, so a cleared
          persona must see every row the owner sees.
    (b'') capture-keyed tables have no evidence column at all. Section 6 gates them
          either on a VISIBLE evidence row for the sample (the only direction that
          cannot invert) or, more coarsely, on the capture's own incident -- and the
          two carry different honest expectations, so each table is asserted against
          the mechanism its policy actually uses, read from the catalog.
    (b''') receipt tables clear through their run, which section 8 scopes to the
          persona that created it. "dba sees what the owner sees" is the WRONG
          assertion there and asserting it would demand a cross-persona leak: dba
          legitimately reads nothing of an app engineer's run. The claim asserted
          instead is a partition -- each persona reads exactly the rows of its own
          runs, less any row naming restricted evidence, and NO persona (including
          the run's owner) reads such a row.

    Routing by mechanism rather than by schema is what makes the coverage total.
    Nine of the twelve receipt tables carry no evidence column at all, so an
    evidence-keyed enumeration cannot see them and section 8's run partition would
    go entirely unasserted -- the mechanism protecting proof.run_stages,
    proof.observability_refs and the whole agent family would have no gate.

(c) replay determinism. The same query re-run in a second transaction under the
    same persona returns an identical row set, and the ``SET LOCAL ROLE`` does not
    survive the transaction (``current_user`` is back to the login role after
    ROLLBACK). Transaction-scoped, never session-scoped.

The gate is read-only: it issues SELECT, ``SET LOCAL ROLE`` and ROLLBACK only, and
never DDL (the ``_common.py`` contract). Roles absent, psycopg absent, or the
engine unreachable -> BLOCKED, never FAIL.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-27"
TITLE = "RLS enforcement (D24)"

READ_PATH_TABLES = (
    "casework.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)

# The two derived tables the search arms actually read. Written by the owner, so
# they inherit whatever the owner could see at build time - which is the whole
# reason this gate measures the owner's own RLS exposure below.
DERIVED_TABLES = ("retrieval.documents", "retrieval.chunks")

PERSONA_ROLES = ("persona_app_engineer", "persona_dba", "persona_auditor")
CLEARANCE_GROUP = "can_see_restricted"

# The three schemas section 2 grants SELECT on, schema-wide.
GRANTED_SCHEMAS = ("casework", "retrieval", "proof")

# Tables with no reference to protect. Not an exemption list the gate trusts: the
# structural rule below derives "needs protection" from the catalog, and these
# names appear only to make the derivation's verdict legible in the output. A table
# that gains an evidence, capture or run column later starts requiring a policy
# automatically, whether or not anyone updated this comment.
#
#   casework.database_clusters      cluster_id-keyed engine configuration
#   proof.evaluation_queries        the harness's own query set
#   retrieval.search_index_builds   build receipts (counts, model IDs, timings)
UNREFERENCED_BY_DESIGN = (
    "casework.database_clusters",
    "proof.evaluation_queries",
    "retrieval.search_index_builds",
)

# Which tables need a policy, asked of the engine. A table needs one when a
# persona could join it back to evidence -- directly (evidence_id / *_evidence_id),
# through a capture run (capture_id), through a proof run (run_id / agent_run_id),
# or by reading a visibility label off it (acl / acl_visibility).
#
# Derived, never listed. The measured drift this catches: retrieval.search_index_queue
# carries evidence_id and 5 of its 110 rows named restricted evidence, but
# sql/11_roles_rls.sql section 5's loop walks casework only, so the outbox had no
# policy while every persona held SELECT on it.
PROTECTION_RULE_SQL = """
WITH cols AS (
  SELECT n.nspname AS sch, c.relname AS tbl, a.attname AS col
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
   WHERE n.nspname = ANY(%s) AND c.relkind = 'r'
),
classified AS (
  SELECT sch || '.' || tbl AS qualified,
         bool_or(col = 'evidence_id' OR col LIKE '%%\\_evidence\\_id') AS evidence_ref,
         bool_or(col = 'capture_id') AS capture_ref,
         bool_or(col IN ('run_id', 'agent_run_id')) AS run_ref,
         bool_or(col IN ('acl', 'acl_visibility')) AS acl_ref
    FROM cols
   GROUP BY 1
)
SELECT c.qualified,
       (c.evidence_ref OR c.capture_ref OR c.run_ref OR c.acl_ref) AS needs_policy,
       rel.relrowsecurity,
       rel.relforcerowsecurity,
       (SELECT count(*) FROM pg_policies p
         WHERE p.schemaname || '.' || p.tablename = c.qualified) AS policy_count
  FROM classified c
  JOIN pg_class rel ON rel.oid = c.qualified::regclass
 ORDER BY c.qualified
"""

# Restricted rows are measured, never hand-typed: the gate asks the engine which
# rows are restricted, as the owner, then asserts the persona views against that
# measured set.
#
# Both columns, because the two are needed for different jobs. ``evidence_id`` is
# the only identity column present on all three read-path tables --
# ``retrieval.chunks`` has NO ``external_key``, so a probe written against
# ``external_key`` raises UndefinedColumn at the chunks table instead of measuring
# anything. ``external_key`` is what a human can act on, so it is what gets printed.
RESTRICTED_KEYS_SQL = """
SELECT external_key, evidence_id
  FROM casework.evidence_items
 WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
   AND NOT is_deleted
 ORDER BY external_key
"""

# The classification the participant's own run produced, re-derived here from the
# captured payload rather than from the acl column. This is the independent oracle
# for "the restricted cohort is the rows whose capture carried resolved statement
# text" (labs/incident/run_live_workshop.py:_measured_visibility). If the two
# disagree, either someone relabelled evidence by hand or the classifier changed
# without the ACLs being reconciled -- and sql/12_masking.sql reads the same
# payload to build its redaction set, so a drift here silently empties the mask.
CLASSIFICATION_ORACLE_SQL = """
SELECT count(*) FILTER (WHERE carries AND visibility <> 'restricted') AS should_be_restricted,
       count(*) FILTER (WHERE NOT carries AND visibility = 'restricted') AS should_be_workshop,
       count(*) FILTER (WHERE carries) AS carries_statement
  FROM (
    SELECT coalesce(evidence.acl ->> 'visibility', 'restricted') AS visibility,
           telemetry.structured ? 'statement'
             AND btrim(coalesce(telemetry.structured ->> 'statement', '')) <> ''
             AND lower(btrim(coalesce(telemetry.structured ->> 'statement', ''))) <> 'unknown'
             AS carries
      FROM casework.evidence_items evidence
      JOIN casework.telemetry_evidence telemetry
        ON telemetry.evidence_id = evidence.evidence_id
     WHERE NOT evidence.is_deleted
  ) classified
"""

# Probed by evidence_id for the reason above. DISTINCT because retrieval.documents
# and retrieval.chunks hold one row per version per evidence item, not one row per
# item.
VISIBLE_IDS_SQL = """
SELECT DISTINCT evidence_id
  FROM {table}
 WHERE evidence_id = ANY(%s)
"""

DERIVED_RESTRICTED_SQL = """
SELECT count(*) FROM {table} WHERE is_current AND acl_visibility = 'restricted'
"""

# Per-table row counts, measured AS THE OWNER, over rows that touch restricted
# evidence on ANY of their reference columns. This is the independent oracle group
# (b') needs: persona_dba's own view cannot be used to decide whether a table "has
# no restricted rows of this kind", because that view is the fact under test. An
# empty dba result means either the kind genuinely has none or dba's visibility is
# broken, and those need opposite verdicts.
#
# Safe to run as the owner for the reason _diagnose_empty_restricted() documents:
# run() has already proven the owner is either a bypassing role or named by every
# policy AND holding the clearance group, so this count is unfiltered.
EVIDENCE_TOUCH_SQL = "SELECT count(*) FROM {table} WHERE {predicate}"

# Capture-keyed tables have no evidence column, so "restricted" is resolved one hop
# out: which captures built restricted evidence. Resolved HERE, as the owner, and
# then handed to the persona probe as a plain array of ids.
#
# Two reasons the resolution cannot live inside the persona's own query, and the
# second one is severe:
#
# 1. Honesty. A subquery run by a persona is itself RLS-filtered, so a zero from it
#    cannot distinguish "no such capture" from "a capture you may not see" -- the
#    exact inversion section 6's comment documents failing OPEN. The owner reads
#    unfiltered, so its answer is an oracle rather than a restatement of the fact
#    under test.
# 2. pg_columnmask crashes the engine on that shape. On Aurora PostgreSQL 18.3 with
#    pg_columnmask 1.1.0 a masked role JOINING a masked table terminates the backend
#    with signal 11 and restarts the whole instance -- measured 2026-08-02 23:41:07
#    UTC, "client backend was terminated by signal 11: Segmentation fault ... Aurora
#    Runtime process unexpectedly exited", ~90s of downtime for every database on the
#    cluster. Wrapped in EXISTS the same join is merely rejected ("Predicates on
#    masked columns are not allowed"), which is how this gate first hit it. A gate
#    must not be able to take the cluster down, so it never joins a masked table
#    under a persona.
#
#    casework.telemetry_evidence itself is no longer masked -- the same crash reached
#    casework.v_evidence_documents and the shipped app, so sql/12_masking.sql dropped
#    mask_telemetry and G-29's MUST_NOT_BE_MASKED now keeps it dropped. This
#    discipline still stands: the three sample tables ARE masked, the crash shape is
#    a property of pg_columnmask rather than of one policy, and reason 1 alone is
#    sufficient to resolve the oracle as the owner.
RESTRICTED_CAPTURES_SQL = """
SELECT DISTINCT telemetry.capture_id
  FROM casework.telemetry_evidence telemetry
 WHERE telemetry.evidence_id = ANY(%s)
   AND telemetry.capture_id IS NOT NULL
"""

# Bare predicate on an unmasked column, no join: safe under every persona, and it
# measures the sample table's own policy rather than the visibility of whatever the
# join walked through.
CAPTURE_TOUCH_SQL = "SELECT count(*) FROM {table} WHERE capture_id = ANY(%s)"

# Which of section 6's two sub-mechanisms each capture-keyed table uses, read off the
# policy body in the catalog. Asked rather than assumed because the two carry
# DIFFERENT honest expectations and picking the wrong one produces a confidently
# wrong verdict in either direction:
#
# * evidence-row-gated (casework.database_insights_samples) requires a VISIBLE
#   telemetry evidence row matching the sample's own dimension and query_id, so an
#   uncleared persona is denied exactly the samples whose evidence row is restricted.
#   Measured on this capture: 7 samples, 2 visible to app_engineer.
# * capture-run-gated (casework.cloudwatch_metric_samples,
#   casework.pg_stat_statements_samples) requires only that the capture's incident be
#   visible. Section 6 calls this "coarser and deliberately so". Its incident is
#   workshop-visible here, so all 3 personas legitimately read all rows and the
#   statement text is withheld by MASKING, not by RLS.
#
# Asserting app_engineer == 0 on a capture-run-gated table would be asserting a
# guarantee the DDL never made. That assertion did pass before this query existed --
# but only because the probe joined casework.telemetry_evidence INSIDE the persona's
# own transaction, where the join was itself RLS-filtered. The gate was reading its
# own filtering back as the fact under test, which is the same inversion section 6's
# comment documents failing OPEN.
CAPTURE_MECHANISM_SQL = """
SELECT p.schemaname || '.' || p.tablename AS qualified,
       bool_or(p.qual LIKE '%%telemetry_evidence%%') AS evidence_gated,
       bool_or(p.qual LIKE '%%incident_capture_runs%%') AS capture_run_gated
  FROM pg_policies p
 WHERE p.schemaname || '.' || p.tablename = ANY(%s)
   AND p.policyname LIKE 'rls\\_%%'
 GROUP BY 1
"""

# The owner's oracle for an evidence-row-gated table: how many samples an UNCLEARED
# persona should reach, being those whose matching telemetry evidence row is
# workshop-visible. Mirrors section 6's predicate exactly, with the visibility test
# the persona's RLS would have applied made explicit instead of implicit -- so the
# expectation is computed unfiltered and cannot inherit the filtering it checks.
EVIDENCE_VISIBLE_SQL = """
SELECT count(*) FILTER (WHERE visible_workshop) AS uncleared,
       count(*) FILTER (WHERE visible_any) AS cleared
  FROM (
    SELECT
      EXISTS (
        SELECT 1
          FROM casework.telemetry_evidence evidence_row
          JOIN casework.evidence_items evidence
            ON evidence.evidence_id = evidence_row.evidence_id
         WHERE evidence_row.capture_id = sample.capture_id
           AND evidence_row.telemetry_type = 'database_insights'
           AND evidence_row.structured ->> 'dimension' = sample.dimension
           AND NOT (evidence_row.structured ->> 'query_id'
                    IS DISTINCT FROM sample.query_id)
           AND coalesce(evidence.acl ->> 'visibility', 'restricted') = 'workshop'
      ) AS visible_workshop,
      EXISTS (
        SELECT 1
          FROM casework.telemetry_evidence evidence_row
         WHERE evidence_row.capture_id = sample.capture_id
           AND evidence_row.telemetry_type = 'database_insights'
           AND evidence_row.structured ->> 'dimension' = sample.dimension
           AND NOT (evidence_row.structured ->> 'query_id'
                    IS DISTINCT FROM sample.query_id)
      ) AS visible_any
      FROM {table} sample
     WHERE sample.capture_id = ANY(%s)
  ) classified
"""

# The same oracle for a capture-run-gated table: visibility turns on the capture's
# incident, so ``uncleared`` counts samples whose incident is workshop-visible.
CAPTURE_RUN_VISIBLE_SQL = """
SELECT count(*) FILTER (WHERE visible_workshop) AS uncleared,
       count(*) FILTER (WHERE visible_any) AS cleared
  FROM (
    SELECT
      EXISTS (
        SELECT 1
          FROM casework.incident_capture_runs run
          JOIN casework.evidence_items evidence
            ON evidence.evidence_id = run.incident_evidence_id
         WHERE run.capture_id = sample.capture_id
           AND coalesce(evidence.acl ->> 'visibility', 'restricted') = 'workshop'
      ) AS visible_workshop,
      EXISTS (
        SELECT 1
          FROM casework.incident_capture_runs run
         WHERE run.capture_id = sample.capture_id
      ) AS visible_any
      FROM {table} sample
     WHERE sample.capture_id = ANY(%s)
  ) classified
"""

# The owner's own exposure to the policies it created. ``listed_on`` is the set of
# read-path tables whose policy names this role (directly or through PUBLIC);
# ``has_clearance`` is the second half. Neither is cosmetic: see
# _diagnose_empty_restricted.
OWNER_EXPOSURE_SQL = """
SELECT
    current_user::text AS owner,
    coalesce((SELECT rolsuper      FROM pg_roles WHERE rolname = current_user), false)
      AS is_super,
    coalesce((SELECT rolbypassrls  FROM pg_roles WHERE rolname = current_user), false)
      AS bypasses_rls,
    coalesce((
      SELECT array_agg(DISTINCT schemaname || '.' || tablename)
        FROM pg_policies
       WHERE schemaname || '.' || tablename = ANY(%s)
         AND (current_user = ANY(roles) OR 'public' = ANY(roles))
    ), '{}'::text[]) AS listed_on
"""

# Membership resolved through pg_roles by OID, never by naming the role inside
# pg_has_role() directly.
#
# ``pg_has_role(current_user, 'some_role', 'USAGE')`` raises UndefinedObject (42704)
# when the role does not exist, and it raises at PLAN time -- so no boolean
# short-circuit, CASE arm or EXISTS guard can save it; the whole statement dies
# before a row is produced. The subselect form yields NULL instead, which coalesce
# turns into false. This matters most for ``rds_superuser``, which exists ONLY on
# Aurora/RDS: measured on PG17, the bare call turned this gate's honest report into
# an unhandled traceback (`role "rds_superuser" does not exist`) on every local
# cluster and disposable test database.
MEMBER_OF_SQL = """
SELECT coalesce(
  (SELECT pg_has_role(current_user, oid, 'USAGE') FROM pg_roles WHERE rolname = %s),
  false
)
"""

# The reference columns each protected table carries, so the gate can build the
# same OR-of-endpoints predicate the owner oracle and the persona probe both use.
REFERENCE_COLUMNS_SQL = """
SELECT n.nspname || '.' || c.relname AS qualified,
       array_agg(a.attname ORDER BY a.attnum) AS columns
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
 WHERE n.nspname = ANY(%s)
   AND c.relkind = 'r'
   AND (a.attname = 'evidence_id' OR a.attname LIKE '%%\\_evidence\\_id')
 GROUP BY 1
 ORDER BY 1
"""

# Run-gated tables: anything carrying run_id or agent_run_id. Section 8 chains every
# receipt row's visibility to the persona named on its root run, so these clear
# through a DIFFERENT mechanism than the evidence-keyed tables and need their own
# assertion. Enumerated from the catalog for the same reason as everything else here:
# nine of the twelve carry no evidence column, so an evidence-keyed enumeration is
# structurally blind to them.
#
# Nullability is selected, not assumed, because _run_root() joins on these keys and an
# inner join through a nullable one drops rows -- which would understate the owner
# oracle and turn a real leak into a passing subtraction. Measured on this schema:
# proof.agent_answers.agent_run_id and proof.transport_invocations.run_id are both
# nullable, and both carry a NOT NULL alternative the resolver prefers.
RUN_GATED_SQL = """
SELECT n.nspname || '.' || c.relname AS qualified,
       bool_or(a.attname = 'role') AS carries_role,
       bool_or(a.attname = 'run_id' AND a.attnotnull) AS run_id_required,
       bool_or(a.attname = 'agent_run_id' AND a.attnotnull) AS agent_run_id_required,
       bool_or(a.attname = 'evidence_id') AS evidence_ref
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
 WHERE n.nspname = ANY(%s)
   AND c.relkind = 'r'
 GROUP BY 1
HAVING bool_or(a.attname IN ('run_id', 'agent_run_id'))
 ORDER BY 1
"""

# The owner's oracle for one run-gated table: how its rows partition across the
# personas owning their root runs, and how many of each slice name restricted
# evidence. Both halves are needed -- the total is what a persona must read, the
# touching count is what must be subtracted from an uncleared one.
#
# {root_join} is empty for a table carrying ``role`` itself (it IS its own root, and
# {role_expr} then reads the column directly) and a JOIN to proof.retrieval_runs or
# proof.agent_runs otherwise. {evidence_expr} is ``NULL::uuid`` for the nine tables
# with no evidence column, which makes the FILTER count 0 without a second statement
# shape to keep in sync.
RUN_PARTITION_SQL = """
SELECT {role_expr} AS role,
       count(*) AS total,
       count(*) FILTER (WHERE {evidence_expr} = ANY(%s::uuid[])) AS touching
  FROM {table} child{root_join}
 GROUP BY 1
 ORDER BY 1
"""

# What a persona actually reads at a run-gated table: the raw count, with no join to
# the root. Deliberately unjoined -- joining to proof.retrieval_runs would apply that
# table's policy too and a child policy that admits everything would still measure
# clean, because the join would do the filtering the child policy was supposed to do.
RUN_GATED_COUNT_SQL = "SELECT count(*) FROM {table}"

RUN_GATED_RESTRICTED_SQL = (
    "SELECT count(*) FROM {table} WHERE evidence_id = ANY(%s::uuid[])"
)

# Capture-keyed tables: a capture_id and no evidence reference at all.
CAPTURE_ONLY_SQL = """
SELECT n.nspname || '.' || c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = ANY(%s)
   AND c.relkind = 'r'
   AND EXISTS (
     SELECT 1 FROM pg_attribute a
      WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        AND a.attname = 'capture_id'
   )
   AND NOT EXISTS (
     SELECT 1 FROM pg_attribute a
      WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        AND (a.attname = 'evidence_id' OR a.attname LIKE '%%\\_evidence\\_id')
   )
 ORDER BY 1
"""


def _roles_present(cur, names: tuple[str, ...]) -> list[str]:
    cur.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        [list(names)],
    )
    return [row[0] for row in cur.fetchall()]


def _member_of(cur, role: str) -> bool:
    """Return whether ``current_user`` is a USAGE member of ``role``.

    False when ``role`` does not exist on this cluster. See MEMBER_OF_SQL.
    """
    cur.execute(MEMBER_OF_SQL, [role])
    return cur.fetchone()[0]


def _touch_predicate(columns: list[str]) -> str:
    """Return the OR-of-endpoints predicate for a table's reference columns.

    OR, not AND: a row "touches restricted evidence" when ANY endpoint is
    restricted, which is the set section 5's AND-of-endpoints policy must hide in
    full. Building the two from the same column list is what keeps the oracle and
    the assertion measuring the same rows.
    """
    return " OR ".join(f"{column} = ANY(%s)" for column in columns)


def _run_root(entry: dict) -> str:
    """Return the JOIN clause reaching ``entry``'s run-owning root, or ''.

    Section 8 chains visibility from a root run that carries ``role`` to children
    that carry only a run key, so the owner oracle has to walk the same chain to know
    which persona a child row belongs to.

    A NOT NULL key is required, not preferred: an inner join through a nullable one
    silently drops rows, understating the oracle and letting a leak pass as a
    subtraction. ``agent_run_id`` is checked first because the agent tables that
    carry both keys hang off proof.agent_runs.

    Args:
        entry: One RUN_GATED_SQL row as a dict.

    Returns:
        '' when the table carries ``role`` itself, otherwise a JOIN aliasing the root
        as ``root``.

    Raises:
        RuntimeError: The table carries neither ``role`` nor a NOT NULL run key, so
            no unambiguous owner exists and no honest assertion can be made.
    """
    if entry["carries_role"]:
        return ""
    if entry["agent_run_id_required"]:
        return (
            "\n  JOIN proof.agent_runs root"
            " ON root.agent_run_id = child.agent_run_id"
        )
    if entry["run_id_required"]:
        return "\n  JOIN proof.retrieval_runs root ON root.run_id = child.run_id"
    raise RuntimeError(
        f"{entry['table']} is run-gated but carries neither a role column nor a "
        f"NOT NULL run key, so its rows have no unambiguous owning persona. "
        f"Section 8 of sql/11_roles_rls.sql cannot chain visibility for it and this "
        f"gate cannot assert the partition; give the run key NOT NULL or exclude the "
        f"table from the granted schemas"
    )


def _run_partition(cur, entry: dict, ids: list) -> dict[str, tuple[int, int]]:
    """Measure one run-gated table's rows as the owner, per owning persona.

    Returns:
        ``role -> (total, touching_restricted_evidence)``.
    """
    cur.execute(
        RUN_PARTITION_SQL.format(
            table=entry["table"],
            root_join=_run_root(entry),
            role_expr="child.role" if entry["carries_role"] else "root.role",
            evidence_expr=(
                "child.evidence_id" if entry["evidence_ref"] else "NULL::uuid"
            ),
        ),
        [ids],
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _rows_touching(cur, table: str, columns: list[str], ids: list) -> int:
    """Count rows at ``table`` whose reference columns name any of ``ids``."""
    cur.execute(
        EVIDENCE_TOUCH_SQL.format(
            table=table, predicate=_touch_predicate(columns)
        ),
        [ids] * len(columns),
    )
    return cur.fetchone()[0]


def _count_under_persona(conn, persona: str, statement: str, params: list) -> int:
    """Run one counting SELECT under ``persona``. Read-only, always rolled back."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(statement, params)
            return cur.fetchone()[0]
        finally:
            cur.execute("ROLLBACK")


def _ids_under_persona(conn, persona: str, table: str, ids: list) -> set:
    """Return which of ``ids`` ``persona`` can see at ``table``. Read-only."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(VISIBLE_IDS_SQL.format(table=table), [ids])
            return {row[0] for row in cur.fetchall()}
        finally:
            cur.execute("ROLLBACK")


def _denied_without_role(conn, table: str) -> str | None:
    """Return the SQLSTATE raised by a bare SELECT, or None if it succeeded."""
    import psycopg

    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            return None
        except psycopg.errors.InsufficientPrivilege as exc:
            return exc.sqlstate
        finally:
            cur.execute("ROLLBACK")


def _owner_exposure(cur) -> dict:
    """Measure the owner's own exposure to the policies it created."""
    cur.execute(OWNER_EXPOSURE_SQL, [list(READ_PATH_TABLES)])
    owner, is_super, bypasses_rls, listed_on = cur.fetchone()
    return {
        "owner": owner,
        "is_super": is_super,
        "bypasses_rls": bypasses_rls,
        "has_clearance": _member_of(cur, CLEARANCE_GROUP),
        "listed_on": list(listed_on),
    }


def _diagnose_empty_restricted(exposure: dict) -> str:
    """Name the cause when the owner measures zero restricted rows.

    "No restricted rows" has two entirely different causes and reporting the
    wrong one sends the fix to the wrong file:

    * the capture genuinely produced none -> re-run ``make live-workshop``;
    * the owner is being filtered by the policies it created -> fix
      ``sql/11_roles_rls.sql``.

    The second is the dangerous one. Every derived evidence row is written by this
    identity, so a filtered owner silently truncates ``retrieval.documents`` and
    ``retrieval.chunks`` while reporting success (measured on PG17: 1 of 2 rows
    copied, exit 0). The row-filtering assertions below would then be true and
    meaningless. A superuser or ``BYPASSRLS`` owner cannot be in that state, which
    is what makes the first branch safe to attribute to the capture.
    """
    if exposure["is_super"] or exposure["bypasses_rls"]:
        return (
            f"the capture holds no restricted evidence. {exposure['owner']} "
            f"bypasses RLS (rolsuper={exposure['is_super']}, "
            f"rolbypassrls={exposure['bypasses_rls']}), so it read the table "
            f"unfiltered and the absence is real: this run's Performance Insights "
            f"capture resolved no statement text, so nothing was classified "
            f"restricted (labs/incident/run_live_workshop.py:_measured_visibility). "
            f"Re-run make live-workshop against a cluster with Database Insights "
            f"advanced mode enabled"
        )
    unlisted = [t for t in READ_PATH_TABLES if t not in exposure["listed_on"]]
    if unlisted:
        return (
            f"{exposure['owner']} is not named by the policy on "
            f"{', '.join(unlisted)} and is subject to FORCE, so it sees ZERO rows "
            f"there -- this measurement is of a table the owner cannot read, not of "
            f"the capture. Add CURRENT_USER to those policies' TO lists "
            f"(sql/11_roles_rls.sql section 4)"
        )
    if not exposure["has_clearance"]:
        return (
            f"{exposure['owner']} is named by every policy but does NOT hold "
            f"{CLEARANCE_GROUP}, so it reads workshop rows only. The restricted "
            f"cohort exists and is invisible to the identity that writes every "
            f"derived evidence. Restore the "
            f"GRANT {CLEARANCE_GROUP} TO current_user block in sql/11_roles_rls.sql"
        )
    return (
        f"{exposure['owner']} is named by every policy and holds "
        f"{CLEARANCE_GROUP}, so it is reading unfiltered: the capture holds no "
        f"restricted evidence. Re-run make live-workshop against a cluster with "
        f"Database Insights advanced mode enabled"
    )


def _measure_protection(cur) -> tuple[list[dict], str | None]:
    """Ask the catalog which tables need a policy and which lack one.

    Returns:
        ``(protection, blocked_reason)``. ``blocked_reason`` is non-None when a table
        that needs a policy has not got RLS enabled+forced yet, which is a
        not-applied-yet schema rather than a failing one.
    """
    cur.execute(PROTECTION_RULE_SQL, [list(GRANTED_SCHEMAS)])
    protection = [
        {
            "table": row[0],
            "needs_policy": row[1],
            "enabled": row[2],
            "forced": row[3],
            "policies": row[4],
        }
        for row in cur.fetchall()
    ]
    unprotected = [
        entry["table"]
        for entry in protection
        if entry["needs_policy"]
        and not (entry["enabled"] and entry["forced"] and entry["policies"])
    ]
    if unprotected:
        return protection, f"RLS not enabled+forced yet on: {', '.join(unprotected)}"
    return protection, None


def _measure_run_gated(cur, restricted_ids: list) -> list[dict]:
    """Enumerate the run-gated receipt tables and partition each by owning persona."""
    cur.execute(RUN_GATED_SQL, [list(GRANTED_SCHEMAS)])
    run_gated = [
        {
            "table": row[0],
            "carries_role": row[1],
            "run_id_required": row[2],
            "agent_run_id_required": row[3],
            "evidence_ref": row[4],
        }
        for row in cur.fetchall()
    ]
    for entry in run_gated:
        entry["partition"] = _run_partition(cur, entry, restricted_ids)
    return run_gated


def _measure_capture_keyed(cur, tables: list[str], captures: list) -> dict[str, dict]:
    """Measure each capture-keyed table against the mechanism its policy uses.

    ``uncleared`` and ``cleared`` are the counts an uncleared and a cleared persona
    should reach, computed unfiltered from the same shape section 6's predicate uses.
    Both are None when the mechanism could not be recognized, which the assertion
    reports rather than silently skipping.
    """
    cur.execute(CAPTURE_MECHANISM_SQL, [tables])
    mechanisms = {
        row[0]: "evidence_row" if row[1] else "capture_run" if row[2] else "unrecognized"
        for row in cur.fetchall()
    }
    measured = {}
    for table in tables:
        cur.execute(CAPTURE_TOUCH_SQL.format(table=table), [captures])
        owner_count = cur.fetchone()[0]
        mechanism = mechanisms.get(table, "unpoliced")
        oracle_sql = {
            "evidence_row": EVIDENCE_VISIBLE_SQL,
            "capture_run": CAPTURE_RUN_VISIBLE_SQL,
        }.get(mechanism)
        uncleared = cleared = None
        if oracle_sql:
            cur.execute(oracle_sql.format(table=table), [captures])
            uncleared, cleared = cur.fetchone()
        measured[table] = {
            "owner": owner_count,
            "mechanism": mechanism,
            "uncleared": uncleared,
            "cleared": cleared,
        }
    return measured


def _measure_classification(cur) -> dict:
    """Measure the restricted set, its classification oracle, and derived rows."""
    cur.execute(RESTRICTED_KEYS_SQL)
    rows = cur.fetchall()
    cur.execute(CLASSIFICATION_ORACLE_SQL)
    oracle = dict(
        zip(
            ("should_be_restricted", "should_be_workshop", "carries"),
            cur.fetchone(),
        )
    )
    derived = {}
    for table in DERIVED_TABLES:
        cur.execute(DERIVED_RESTRICTED_SQL.format(table=table))
        derived[table] = cur.fetchone()[0]
    return {
        "restricted_keys": [row[0] for row in rows],
        "restricted_ids": [row[1] for row in rows],
        "oracle": oracle,
        "derived": derived,
    }


def _measure_by_mechanism(cur, restricted_ids: list) -> dict:
    """Route every protected table to its mechanism and measure the owner's oracle.

    Run-gated first: a table is routed by mechanism, so the ones section 8 chains
    through a run are removed from the evidence-keyed group rather than asserted
    twice under two incompatible rules.
    """
    cur.execute(REFERENCE_COLUMNS_SQL, [list(GRANTED_SCHEMAS)])
    reference_columns = {row[0]: list(row[1]) for row in cur.fetchall()}
    cur.execute(CAPTURE_ONLY_SQL, [list(GRANTED_SCHEMAS)])
    capture_tables = [row[0] for row in cur.fetchall()]

    run_gated = _measure_run_gated(cur, restricted_ids)
    run_gated_names = {entry["table"] for entry in run_gated}
    evidence_touch = {
        table: _rows_touching(cur, table, columns, restricted_ids)
        for table, columns in reference_columns.items()
        if table not in READ_PATH_TABLES and table not in run_gated_names
    }
    # One hop out, as the owner: the captures that built restricted evidence.
    # See RESTRICTED_CAPTURES_SQL for why this cannot be folded into the persona
    # probe.
    cur.execute(RESTRICTED_CAPTURES_SQL, [restricted_ids])
    restricted_captures = [row[0] for row in cur.fetchall()]
    return {
        "reference_columns": reference_columns,
        "capture_tables": capture_tables,
        "restricted_captures": restricted_captures,
        "evidence_touch": evidence_touch,
        "capture_touch": _measure_capture_keyed(
            cur, capture_tables, restricted_captures
        ),
        "run_gated": run_gated,
    }


def _measure_as_owner(psycopg, owner_dsn: str) -> dict | str:
    """Measure everything that must be read unfiltered. Returns a str on BLOCKED."""
    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            wanted = PERSONA_ROLES + (CLEARANCE_GROUP,)
            missing = sorted(set(wanted) - set(_roles_present(cur, wanted)))
            if missing:
                return f"roles not created yet: {', '.join(missing)}"

            protection, blocked = _measure_protection(cur)
            if blocked:
                return blocked

            measured = {"protection": protection, "exposure": _owner_exposure(cur)}
            measured.update(_measure_classification(cur))
            measured.update(_measure_by_mechanism(cur, measured["restricted_ids"]))
    return measured


def _report_protection_rule(protection: list[dict]) -> None:
    """Print the catalog-derived protection verdict for every table."""
    print("\n  protection rule (derived from the catalog, not listed):")
    for entry in protection:
        note = ""
        if not entry["needs_policy"]:
            note = " (no evidence, capture, run or acl reference)"
        print(
            f"    {entry['table']:<40} needs={str(entry['needs_policy']):<5} "
            f"enabled={entry['enabled']} forced={entry['forced']} "
            f"policies={entry['policies']}{note}"
        )


def _assert_classification(oracle: dict, restricted: list[str]) -> None:
    """Assert the ACLs still agree with what the capture actually contains."""
    print(
        f"\n  classification oracle: {oracle['carries']} telemetry rows carry "
        f"resolved statement text; {len(restricted)} rows are labelled restricted"
    )
    require(
        oracle["should_be_restricted"] == 0,
        f"{oracle['should_be_restricted']} evidence rows carry resolved captured "
        f"statement text but are labelled workshop. The ACL and the capture "
        f"disagree, so sql/12_masking.sql builds its redaction set from statements "
        f"that RLS is not withholding. Re-run sql/01_schema.sql to reconcile the "
        f"ACLs, or fix labs/incident/run_live_workshop.py:_measured_visibility",
    )
    require(
        oracle["should_be_workshop"] == 0,
        f"{oracle['should_be_workshop']} evidence rows are labelled restricted "
        f"while their capture carries no resolved statement text. The workshop's "
        f"claim is that restriction is measured from the capture, not asserted by "
        f"hand; a row restricted for no captured reason breaks that claim",
    )


def _assert_fail_closed(conn, cur_factory) -> str:
    """Assert the pool login has no standing privilege path. Returns its name."""
    with cur_factory() as cur:
        cur.execute("SELECT current_user")
        login = cur.fetchone()[0]
        # Resolved through pg_roles: rds_superuser exists only on Aurora/RDS and
        # naming it inside pg_has_role() aborts the statement elsewhere.
        is_master = _member_of(cur, "rds_superuser")
        cur.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        bypasses = cur.fetchone()[0]
    print(f"    connected as: {login} (rds_superuser member: {is_master})")
    require(
        not is_master,
        f"{login} is an rds_superuser member; a cluster-master identity can grant "
        f"itself the clearance key at will, so the pool must not be one",
    )
    require(bypasses is False, f"{login} has BYPASSRLS; the pool identity must not")
    for table in READ_PATH_TABLES:
        sqlstate = _denied_without_role(conn, table)
        print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
        require(
            sqlstate == "42501",
            f"bare SELECT on {table} as {login} did not raise permission denied "
            f"(got {sqlstate or 'success'}); the pool fails OPEN",
        )
    return login


def _assert_read_path_filtering(app_conn, restricted_ids: list) -> None:
    """Group (b): the three tables every search arm reads."""
    print("\n  (b) row filtering at the read-path tables:")
    for table in READ_PATH_TABLES:
        seen = {
            persona: _ids_under_persona(app_conn, persona, table, restricted_ids)
            for persona in PERSONA_ROLES
        }
        print(
            f"    {table}: "
            + " ".join(f"{p.removeprefix('persona_')}={len(v)}" for p, v in seen.items())
            + f" (of {len(restricted_ids)} restricted)"
        )
        require(
            seen["persona_app_engineer"] == set(),
            f"persona_app_engineer saw restricted rows at {table}: "
            f"{sorted(str(i) for i in seen['persona_app_engineer'])}",
        )
        require(
            seen["persona_dba"],
            f"persona_dba saw no restricted rows at {table}; the clearance grant "
            f"is missing",
        )
        require(
            seen["persona_auditor"],
            f"persona_auditor saw no restricted rows at {table}; masking needs the "
            f"row present",
        )


def _assert_evidence_keyed_filtering(app_conn, measured: dict) -> None:
    """Group (b'): every other evidence-keyed table, discovered from the catalog.

    Scoped to the tables that clear through casework.evidence_items alone. Receipt
    tables carrying a run key are routed to _assert_run_gated_filtering() instead,
    because there the cleared-persona equality asserted below would demand a
    cross-persona leak rather than forbid one.
    """
    restricted_ids = measured["restricted_ids"]
    touch = measured["evidence_touch"]
    print("\n  owner reach into the evidence-keyed tables (oracle sanity):")
    for table, count in sorted(touch.items()):
        columns = ", ".join(measured["reference_columns"][table])
        print(f"    {table}: {count} rows touch restricted evidence via {columns}")
    require(
        any(count > 0 for count in touch.values()),
        f"the owner measured 0 rows touching restricted evidence across all "
        f"{len(touch)} evidence-keyed tables while casework.evidence_items holds "
        f"{len(restricted_ids)} restricted rows. Every table would then take the "
        f"skip branch below and the group would report clean over policies that "
        f"deny every persona. The owner is being filtered by the policies it "
        f"created: check that section 5's generated TO lists still include "
        f"CURRENT_USER and that make security-schema ran as the same identity this "
        f"gate connects as (sql/11_roles_rls.sql section 5)",
    )

    print("\n  (b') row filtering at the evidence-keyed tables:")
    for table, owner_count in sorted(touch.items()):
        columns = measured["reference_columns"][table]
        statement = EVIDENCE_TOUCH_SQL.format(
            table=table, predicate=_touch_predicate(columns)
        )
        params = [restricted_ids] * len(columns)
        seen = {
            persona: _count_under_persona(app_conn, persona, statement, params)
            for persona in PERSONA_ROLES
        }
        print(
            f"    {table}: "
            + " ".join(f"{p.removeprefix('persona_')}={v}" for p, v in seen.items())
            + f" (owner={owner_count})"
        )
        require(
            seen["persona_app_engineer"] == 0,
            f"persona_app_engineer read {seen['persona_app_engineer']} rows touching "
            f"restricted evidence out of {table}. Section 2 of sql/11_roles_rls.sql "
            f"grants every persona SELECT ON ALL TABLES IN SCHEMA "
            f"{table.split('.')[0]}, so the app engineer is denied at "
            f"casework.evidence_items and then reads the same evidence here. The "
            f"policy must AND an EXISTS on casework.evidence_items for EVERY "
            f"reference column this table carries ({', '.join(columns)}) -- a "
            f"single-endpoint predicate passes every row whose other endpoint the "
            f"app engineer can already see (sql/11_roles_rls.sql sections 5 and 7)",
        )
        # The OWNER's count decides whether to skip, not persona_dba's. An empty
        # dba view is the failure this group exists to catch when the rows are
        # actually there, and a legitimate skip when they are not -- persona_dba
        # cannot distinguish those two states about itself.
        if owner_count == 0:
            print("      (relates no restricted evidence; app-engineer-only check)")
            continue
        require(
            seen["persona_dba"] == owner_count,
            f"persona_dba read {seen['persona_dba']} of the {owner_count} rows the "
            f"owner measured at {table}. Either persona_dba is missing from that "
            f"table's policy TO list or a reference column in the predicate is "
            f"wrong (sql/11_roles_rls.sql sections 5 and 7). Without this "
            f"assertion the gate would report PASS over a policy that denies every "
            f"persona",
        )
        require(
            seen["persona_auditor"] == owner_count,
            f"persona_auditor read {seen['persona_auditor']} of the {owner_count} "
            f"rows at {table} while persona_dba read {seen['persona_dba']}; the two "
            f"personas hold the same clearance and differ only in masking, which "
            f"does not filter rows",
        )


def _assert_capture_mechanism(table: str, mechanism: str) -> None:
    """Assert the table's policy names one of section 6's two visibility gates."""
    require(
        mechanism in ("evidence_row", "capture_run"),
        f"{table} is keyed by capture_id and holds capture payloads, but its RLS "
        f"policy references neither casework.telemetry_evidence (a visible "
        f"evidence row) nor casework.incident_capture_runs (the capture's incident) "
        f"-- so this gate cannot tell what visibility it is supposed to enforce, "
        f"and section 2 grants every persona SELECT on the schema regardless. "
        f"Gate it on one of section 6's two shapes (sql/11_roles_rls.sql "
        f"section 6); mechanism resolved as {mechanism!r}",
    )


def _assert_capture_visibility(table: str, entry: dict, seen: dict) -> None:
    """Assert one capture-keyed table against the oracle its own mechanism implies."""
    owner_count = entry["owner"]
    mechanism = entry["mechanism"]
    require(
        seen["persona_app_engineer"] == entry["uncleared"],
        f"persona_app_engineer read {seen['persona_app_engineer']} of the "
        f"{owner_count} samples at {table}, but the owner measured "
        f"{entry['uncleared']} whose visibility gate is workshop-visible. "
        + (
            f"Section 6's predicate must REQUIRE a visible evidence row: a "
            f"`NOT EXISTS (...) OR EXISTS (...)` shape fails OPEN, because an "
            f"RLS-filtered subquery cannot tell 'no such row' from 'a row you may "
            f"not see'"
            if mechanism == "evidence_row"
            else f"This table is gated on its capture's incident, so a divergence "
            f"means the incident's own ACL and this policy disagree"
        )
        + " (sql/11_roles_rls.sql section 6)",
    )
    for persona in ("persona_dba", "persona_auditor"):
        require(
            seen[persona] == entry["cleared"],
            f"{persona} read {seen[persona]} of the {owner_count} samples at "
            f"{table} while the owner measured {entry['cleared']} reachable with "
            f"clearance. A cleared persona must reach every gated sample: the "
            f"auditor's captured statement text is redacted by column masking "
            f"(sql/12_masking.sql), which needs the row present "
            f"(sql/11_roles_rls.sql section 6)",
        )


def _assert_capture_keyed_filtering(app_conn, measured: dict) -> None:
    """Group (b''): capture-keyed tables, which carry no evidence column at all.

    A distinct mechanism, not a repeat of (b'). These tables are keyed by
    ``capture_id`` only, so section 5's catalog loop cannot see them and never will.
    The measured leak before section 6 existed: persona_app_engineer was denied every
    restricted evidence row and then read the identical statements out of
    casework.database_insights_samples one query later.

    Section 6 gates them two different ways, and each is asserted against its OWN
    expectation, read off the policy body in the catalog:

    * evidence-row-gated -- an uncleared persona reads exactly the samples whose
      matching telemetry evidence row is workshop-visible. Restriction here is RLS's
      job and the count is expected to differ between personas.
    * capture-run-gated -- visibility turns only on the capture's incident, which
      section 6 calls "coarser and deliberately so". When that incident is
      workshop-visible all three personas legitimately read every row, and the
      captured statement text is withheld by MASKING (sql/12_masking.sql), not by
      row filtering. Asserting app_engineer == 0 there asserts a guarantee the DDL
      never made.

    Both persona probes are a bare ``capture_id = ANY(...)`` over a key set the OWNER
    resolved, never a join back to casework.telemetry_evidence. Two reasons, and do
    not "simplify" them back into one query:

    * a subquery inside the persona's own transaction is itself RLS-filtered, so the
      gate would read its own filtering back as the fact under test -- which is
      exactly how the blanket app_engineer == 0 above used to pass;
    * a masked role joining a masked table segfaults the Aurora backend and restarts
      the whole instance, and three of the tables this gate probes are masked. See
      RESTRICTED_CAPTURES_SQL for the measurement.
    """
    captures = measured["restricted_captures"]
    touch = measured["capture_touch"]
    print(
        f"\n  (b'') row filtering at the capture-keyed sample tables "
        f"({len(captures)} captures built restricted evidence):"
    )
    require(
        captures,
        f"no capture built any of the {len(measured['restricted_ids'])} restricted "
        f"evidence rows, so every assertion below would hold over an empty key set. "
        f"casework.telemetry_evidence.capture_id is the link this group depends on; a "
        f"capture that wrote evidence without recording its capture_id breaks the tie "
        f"between a sample and the ACL protecting its evidence row "
        f"(labs/incident/run_live_workshop.py)",
    )
    for table in sorted(touch):
        entry = touch[table]
        owner_count = entry["owner"]
        mechanism = entry["mechanism"]
        statement = CAPTURE_TOUCH_SQL.format(table=table)
        seen = {
            persona: _count_under_persona(app_conn, persona, statement, [captures])
            for persona in PERSONA_ROLES
        }
        print(
            f"    {table} [{mechanism}]: "
            + " ".join(f"{p.removeprefix('persona_')}={v}" for p, v in seen.items())
            + f" (owner={owner_count}, expected uncleared={entry['uncleared']} "
            f"cleared={entry['cleared']})"
        )
        _assert_capture_mechanism(table, mechanism)
        if owner_count == 0:
            print("      (no capture built restricted evidence)")
            continue
        _assert_capture_visibility(table, entry, seen)


def _persona_of(role: str) -> str:
    """Map a run's ``role`` value to the database role that owns its receipts."""
    return f"persona_{role}"


def _assert_run_partition(table: str, partition: dict, seen: dict) -> None:
    """Assert one receipt table's rows partition by the persona owning their run."""
    for role, (total, touching) in partition.items():
        owner_persona = _persona_of(role)
        require(
            owner_persona in PERSONA_ROLES,
            f"{table} holds {total} rows whose run names role={role!r}, which is "
            f"not one of the three personas. Section 8's policy CASE maps only "
            f"app_engineer, dba and auditor and returns NULL otherwise, so those "
            f"rows are readable by NO persona and the receipt is unreplayable "
            f"(sql/11_roles_rls.sql section 8)",
        )
        require(
            seen[owner_persona] == total - touching,
            f"{owner_persona} read {seen[owner_persona]} rows at {table} but owns "
            f"{total} runs' worth, of which {touching} name restricted evidence "
            f"-- so it should read exactly {total - touching}. "
            + (
                f"Reading more means the evidence clause is missing: section 8 "
                f"appends it from the catalog, and without it a run's own owner "
                f"reads restricted evidence back out of its own receipt"
                if seen[owner_persona] > total - touching
                else f"Reading fewer means the run predicate is denying rows the "
                f"persona created, so its own receipt is unreplayable"
            )
            + " (sql/11_roles_rls.sql section 8)",
        )

    for persona in PERSONA_ROLES:
        if persona.removeprefix("persona_") in partition:
            continue
        require(
            seen[persona] == 0,
            f"{persona} read {seen[persona]} rows at {table} while owning none of "
            f"its runs. Receipts are scoped to the persona that created them "
            f"(section 8), and clearance does not widen that: a cleared persona "
            f"reading another persona's receipt is a cross-persona leak, not a "
            f"clearance. Check that the policy's CASE compares against "
            f"current_user and not a constant (sql/11_roles_rls.sql section 8)",
        )


def _assert_receipt_names_no_restricted(
    app_conn, table: str, restricted_ids: list, owner_touching: int
) -> None:
    """Assert no persona reads a receipt row naming restricted evidence."""
    statement = RUN_GATED_RESTRICTED_SQL.format(table=table)
    seen = {
        persona: _count_under_persona(app_conn, persona, statement, [restricted_ids])
        for persona in PERSONA_ROLES
    }
    print(
        "      naming restricted evidence: "
        + " ".join(f"{p.removeprefix('persona_')}={v}" for p, v in seen.items())
        + f" (owner={owner_touching}, must be 0 for every persona)"
    )
    for persona, count in seen.items():
        require(
            count == 0,
            f"{persona} read {count} rows at {table} naming restricted evidence. "
            f"A receipt outlives the visibility context that produced it and the "
            f"ACL can change underneath it, so clearing through the run is "
            f"necessary and NOT sufficient: the row must clear through the "
            f"EVIDENCE too. This is the measured leak -- "
            f"proof.retrieval_candidates.evidence_snapshot holds the document "
            f"header and chunk snippet as retrieved, so the restricted statement "
            f"text RLS withheld at casework.evidence_items came back out of a run "
            f"the reader owned. Restore the catalog-derived evidence clause in "
            f"sql/11_roles_rls.sql section 8",
        )


def _report_run_partition(table: str, partition: dict, seen: dict) -> tuple[int, int]:
    """Print one receipt table's persona counts beside the owner's partition.

    Returns:
        ``(owner_total, owner_touching)`` -- the rows the owner reads across every
        slice, and how many of them name restricted evidence.
    """
    owner_total = sum(total for total, _ in partition.values())
    owner_touching = sum(touching for _, touching in partition.values())
    slices = ", ".join(f"{role}:{t}" for role, (t, _) in sorted(partition.items()))
    read = " ".join(f"{p.removeprefix('persona_')}={v}" for p, v in seen.items())
    print(
        f"    {table}: {read} (owner={owner_total} in {slices or 'no runs'}, "
        f"{owner_touching} naming restricted evidence)"
    )
    return owner_total, owner_touching


def _assert_run_gated_filtering(app_conn, measured: dict) -> None:
    """Group (b'''): receipt tables, which clear through their run, not evidence.

    A third mechanism, and the one with no coverage before this group existed. Nine
    of the twelve run-gated tables carry no evidence column at all, so the
    evidence-keyed enumeration is structurally blind to them and section 8's run
    partition -- the only thing protecting proof.run_stages,
    proof.observability_refs and the whole agent family -- went unasserted.

    The claim is a partition, not a clearance. Section 8 scopes a receipt to the
    persona that created its run, so:

    * the persona owning a slice reads exactly that slice, less any row naming
      restricted evidence (asserted per persona against the owner's oracle);
    * every other persona reads zero of it -- including a CLEARED one, because
      clearance is about evidence and this is about run ownership. Asserting
      "dba sees what the owner sees" here would demand a cross-persona leak;
    * no persona at all reads a row naming restricted evidence, not even the run's
      own owner. That is the measured leak section 8 exists to close:
      proof.retrieval_candidates.evidence_snapshot copied restricted statement text
      into a receipt an App Engineer legitimately owned, so the run predicate passed
      and the text RLS had just withheld came back out.
    """
    restricted_ids = measured["restricted_ids"]
    run_gated = measured["run_gated"]
    print("\n  (b''') row filtering at the run-gated receipt tables:")
    for entry in run_gated:
        table = entry["table"]
        partition = entry["partition"]
        seen = {
            persona: _count_under_persona(
                app_conn, persona, RUN_GATED_COUNT_SQL.format(table=table), []
            )
            for persona in PERSONA_ROLES
        }
        _, owner_touching = _report_run_partition(table, partition, seen)
        _assert_run_partition(table, partition, seen)
        if entry["evidence_ref"]:
            _assert_receipt_names_no_restricted(
                app_conn, table, restricted_ids, owner_touching
            )


def _assert_owner_measurement(measured: dict) -> None:
    """Section (0): report and assert the preconditions every later group rests on."""
    exposure = measured["exposure"]
    restricted = measured["restricted_keys"]
    _report_protection_rule(measured["protection"])

    # Everything below was measured as the owner, so print what the owner could
    # actually see while measuring it. Without this line a zero count reads as "the
    # capture has no restricted evidence" when the truth may be "the writer is blind".
    print(
        f"\n  measuring as: {exposure['owner']} "
        f"(rolsuper={exposure['is_super']} rolbypassrls={exposure['bypasses_rls']} "
        f"{CLEARANCE_GROUP}={exposure['has_clearance']} "
        f"named by {len(exposure['listed_on'])}/{len(READ_PATH_TABLES)} policies)"
    )

    print(f"\n  restricted rows measured on the engine: {len(restricted)}")
    for key in restricted:
        print(f"    {key}")
    # Not "no restricted rows found" -- that names a symptom and sends the fix to
    # the wrong file half the time. _diagnose_empty_restricted names the cause.
    require(restricted, _diagnose_empty_restricted(exposure))
    _assert_classification(measured["oracle"], restricted)

    # The derived evidence must carry the restricted rows too, and this is NOT redundant
    # with (b). A non-superuser owner subject to FORCE but holding no clearance
    # reads a silently truncated source: the search-index build then indexes only
    # workshop rows, and (b) below reports "app_engineer sees 0 restricted rows" --
    # a PASS for the wrong reason, because there is nothing there to filter.
    print("\n  current restricted rows in the derived retrieval tables:")
    for table in DERIVED_TABLES:
        print(f"    {table}: {measured['derived'][table]}")
        require(
            measured["derived"][table] > 0,
            f"{table} holds no current restricted rows while "
            f"casework.evidence_items holds {len(restricted)}. The retrieval index is "
            f"written by {exposure['owner']}, so either the search index has not "
            f"been rebuilt since the capture, or that identity could not see the "
            f"restricted rows when it built it (named by "
            f"{len(exposure['listed_on'])}/{len(READ_PATH_TABLES)} policies, "
            f"{CLEARANCE_GROUP}={exposure['has_clearance']}) and truncated them "
            f"silently. Either way the row-filtering assertions below would hold "
            f"over an empty set",
        )


def _assert_replay_determinism(app_conn, login: str, restricted_ids: list) -> None:
    """Section (c): the same persona replays identically and the role does not leak."""
    print("\n  (c) replay determinism and transaction scope:")
    first = _ids_under_persona(
        app_conn, "persona_dba", READ_PATH_TABLES[0], restricted_ids
    )
    second = _ids_under_persona(
        app_conn, "persona_dba", READ_PATH_TABLES[0], restricted_ids
    )
    print(f"    replay 1: {len(first)} rows / replay 2: {len(second)} rows")
    require(
        first == second,
        f"replay under the same persona diverged: {first} vs {second}",
    )
    with app_conn.cursor() as cur:
        cur.execute("SELECT current_user")
        after = cur.fetchone()[0]
    print(f"    current_user after ROLLBACK: {after}")
    require(
        after == login,
        f"SET LOCAL ROLE leaked past the transaction: current_user={after}",
    )


def _pass_message(measured: dict) -> str:
    """Name every claim the gate just proved, with the counts it proved them over."""
    protected = sum(1 for entry in measured["protection"] if entry["needs_policy"])
    return (
        f"fail-closed on {len(READ_PATH_TABLES)} read-path tables; "
        f"{len(measured['restricted_keys'])} restricted rows hidden from app_engineer "
        f"across {protected} protected tables "
        f"({len(measured['evidence_touch'])} evidence-keyed, "
        f"{len(measured['capture_touch'])} capture-keyed, "
        f"{len(measured['run_gated'])} run-gated), visible to dba+auditor; receipts "
        f"partition by owning persona and name no restricted evidence; "
        f"classification matches the capture; replay deterministic"
    )


def run() -> int:
    print_header(GATE_ID, TITLE)

    owner_dsn = read_env_value("DATABASE_URL")
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not owner_dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "DATABASE_URL is not set (env or .env); cannot reach the engine",
        )

    try:
        import psycopg
    except ImportError:
        return finish(
            GATE_ID, BLOCKED, "psycopg is not importable in this interpreter"
        )

    print(f"  engine: {redact_dsn(owner_dsn)}")

    try:
        measured = _measure_as_owner(psycopg, owner_dsn)
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")
    if isinstance(measured, str):
        return finish(GATE_ID, BLOCKED, measured)

    _assert_owner_measurement(measured)

    if not app_dsn:
        print(
            "\n  (a) fail-closed: SKIPPED - WORKSHOP_APP_DATABASE_URL not set;"
            " cannot connect as the pool identity"
        )
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_APP_DATABASE_URL is not set; (a) fail-closed unprovable",
        )

    print("\n  (a) fail-closed - bare SELECT as the pool login:")
    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app_conn:
        login = _assert_fail_closed(app_conn, app_conn.cursor)
        _assert_read_path_filtering(app_conn, measured["restricted_ids"])
        _assert_evidence_keyed_filtering(app_conn, measured)
        _assert_capture_keyed_filtering(app_conn, measured)
        _assert_run_gated_filtering(app_conn, measured)
        _assert_replay_determinism(app_conn, login, measured["restricted_ids"])

    return finish(GATE_ID, PASS, _pass_message(measured))


if __name__ == "__main__":
    main_guard(run)
