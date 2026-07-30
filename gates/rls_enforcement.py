#!/usr/bin/env python3
"""G-27 - RLS enforcement assertion (D24, A1/A2/A7/A8).

Three parts, in the order a reader should trust them, preceded by a precondition
that has to come first:

(0) the corpus can prove something. Restricted rows exist in
    ``casework.evidence_items`` AND survived into both derived tables, measured on
    the engine rather than hand-typed. This is not bookkeeping: (b) below asserts
    that ``persona_analyst`` sees zero restricted rows, which is trivially true of
    an empty set. The owner's own RLS exposure is measured alongside it, because
    the owner writes every derived projection and a filtered owner truncates them
    while reporting success. A gate that goes green over an empty enforcement claim
    is worse than one that goes red.

(a) fail-closed. Connected as ``workshop_app`` with **no role set**, a SELECT on
    each of the three read-path tables raises ``permission denied``. An error is
    strictly stronger than "returns zero rows": it proves the pool identity has no
    standing privilege path at all, so a forgotten ``SET ROLE`` cannot leak.

(b) row filtering. Under ``SET LOCAL ROLE persona_analyst`` every restricted row
    returns zero rows at each of ``casework.evidence_items``,
    ``retrieval.documents`` and ``retrieval.chunks`` - the raw tables, no arm, no
    application predicate. Under ``persona_admin`` the same rows are present.
    Both retrieval tables matter: ``vector_search`` reads ``retrieval.chunks``
    standalone and ``fuzzy_search`` reads ``retrieval.documents`` standalone, so a
    policy on ``casework.evidence_items`` alone would leak restricted body text
    while headers stayed filtered.

(c) replay determinism. The same query re-run in a second transaction under the
    same persona returns an identical row set, and the ``SET LOCAL ROLE`` does not
    survive the transaction (``current_user`` is back to the login role after
    ROLLBACK). Transaction-scoped, never session-scoped - the T8 pattern.

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

# The evidence detail tables: keyed 1:1 on casework.evidence_items.evidence_id and
# reachable through section 2's schema-wide GRANT SELECT. RLS on the three
# read-path tables above does not cover them, and the sensitive text lives HERE,
# not in the header table -- an analyst denied at casework.evidence_items could
# read CASE-7421's account_name and customer_commitment straight out of
# casework.support_cases. Enumerated from sql/01_schema.sql (:65, :81, :96, :111,
# :163, :340, :352), not from the current restricted cohort: the bypass is the
# schema-wide grant, so any evidence_id-keyed table is a door.
DETAIL_TABLES = (
    "casework.incidents",
    "casework.changes",
    "casework.support_cases",
    "casework.runbooks",
    "casework.lock_evidence",
    "casework.customer_commitments",
    "casework.postmortems",
)

# The five relation junction tables, with the endpoint column pair each one keys
# on. They carry no evidence body -- only a free-text rationale, which is the
# problem: "The restricted case references the same cluster and interval." names
# the relationship the ACL exists to withhold. They also back
# retrieval.evidence_edges, where security_invoker = true is a NO-OP unless RLS is
# enabled on these base tables, so an unprotected junction leaks through
# /v1/evidence/{id} as well as through a bare psql SELECT.
#
# Listed as (table, near_column, far_column) because these tables have NO
# evidence_id column -- DETAIL_TABLES' probes would raise UndefinedColumn here.
# Both endpoints are checked: the measured leak was an edge whose NEAR side was
# visible to the analyst and whose far side was restricted.
JUNCTION_TABLES = (
    ("casework.incident_changes", "incident_evidence_id", "change_evidence_id"),
    ("casework.incident_support_cases", "incident_evidence_id", "case_evidence_id"),
    ("casework.incident_runbooks", "incident_evidence_id", "runbook_evidence_id"),
    ("casework.change_runbooks", "change_evidence_id", "runbook_evidence_id"),
    (
        "casework.support_case_commitments",
        "case_evidence_id",
        "commitment_evidence_id",
    ),
)

# A junction row is "restricted" when EITHER endpoint is. Counted as the owner for
# the same reason DETAIL_RESTRICTED_COUNT_SQL is: a persona's own empty view cannot
# distinguish "this table relates no restricted evidence" from "this persona's
# visibility is broken", and those need opposite verdicts.
JUNCTION_RESTRICTED_SQL = """
SELECT count(*) FROM {table}
 WHERE {near} = ANY(%s) OR {far} = ANY(%s)
"""

PERSONA_ROLES = ("persona_analyst", "persona_admin", "persona_auditor")
CLEARANCE_GROUP = "can_see_restricted"

# The canonical restricted noun (D22 / M3). Row filtering is asserted against
# every restricted row, but this one must always be among them.
CANONICAL_RESTRICTED_KEY = "CASE-7421"

# The detail table CANONICAL_RESTRICTED_KEY lands in (seed/corpus.py:445-471), so
# the owner measuring zero restricted rows there is impossible unless the owner
# itself is being filtered. Used as the positive control for the (b') oracle.
CONTROL_DETAIL_TABLE = "casework.support_cases"

# Restricted rows are measured, never hand-typed: the gate asks the engine which
# rows are restricted, as the owner, then asserts the persona views against that
# measured set.
#
# Both columns, because the two are needed for different jobs. ``evidence_id`` is
# the only identity column present on all three read-path tables --
# ``retrieval.chunks`` has NO ``external_key`` (sql/01_schema.sql:951-999; the key
# lives on ``retrieval.documents``:895 and ``casework.evidence_items``:34), so a
# probe written against ``external_key`` raises UndefinedColumn at the chunks table
# instead of measuring anything. ``external_key`` is what a human can act on, so it
# is what gets printed.
RESTRICTED_KEYS_SQL = """
SELECT external_key, evidence_id
  FROM casework.evidence_items
 WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
   AND NOT is_deleted
 ORDER BY external_key
"""

# Probed by evidence_id for the reason above. DISTINCT because retrieval.documents
# and retrieval.chunks hold one row per version per evidence item, not one row per
# item (UNIQUE (evidence_id, search_index_version, search_document_hash) at :921).
VISIBLE_IDS_SQL = """
SELECT DISTINCT evidence_id
  FROM {table}
 WHERE evidence_id = ANY(%s)
"""

# The two derived tables the search arms actually read. Written by the owner, so
# they inherit whatever the owner could see at build time - which is the whole
# reason this gate measures the owner's own RLS exposure below.
DERIVED_TABLES = ("retrieval.documents", "retrieval.chunks")

PROJECTED_RESTRICTED_SQL = """
SELECT count(*) FROM {table} WHERE is_current AND acl_visibility = 'restricted'
"""

# Per-table restricted-row counts, measured AS THE OWNER. This is the independent
# oracle group (b') needs: persona_admin's own view cannot be used to decide
# whether a table "has no restricted rows of this kind", because that view is the
# fact under test. An empty admin result means either the kind genuinely has none
# or admin's visibility is broken, and those need opposite verdicts.
#
# Safe to run as the owner for the reason _diagnose_empty_restricted() documents:
# run() has already proven the owner is either a bypassing role or named by every
# policy AND holding the clearance group, so this count is unfiltered. If that were
# not true the gate would have failed before reaching group (b').
#
# Joined against the measured restricted evidence_ids rather than re-deriving
# "restricted" from the acl, so this count and group (b')'s probes are measuring
# the same row set by construction.
DETAIL_RESTRICTED_COUNT_SQL = """
SELECT count(*) FROM {table} WHERE evidence_id = ANY(%s)
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


def _roles_present(cur, names: tuple[str, ...]) -> list[str]:
    cur.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        [list(names)],
    )
    return [row[0] for row in cur.fetchall()]


def _rls_state(cur) -> dict[str, tuple[bool, bool]]:
    """Return {qualified_table: (relrowsecurity, relforcerowsecurity)}."""
    cur.execute(
        """
        SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname || '.' || c.relname = ANY(%s)
        """,
        [list(READ_PATH_TABLES + DETAIL_TABLES + _junction_names())],
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _junction_names() -> tuple[str, ...]:
    """Return just the table names from JUNCTION_TABLES."""
    return tuple(table for table, _near, _far in JUNCTION_TABLES)


def _junction_rows_under_persona(
    conn, persona: str, table: str, near: str, far: str, ids: list
) -> int:
    """Count junction rows touching ``ids`` that ``persona`` can read. Read-only."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(
                JUNCTION_RESTRICTED_SQL.format(table=table, near=near, far=far),
                [ids, ids],
            )
            return cur.fetchone()[0]
        finally:
            cur.execute("ROLLBACK")


def _member_of(cur, role: str) -> bool:
    """Return whether ``current_user`` is a USAGE member of ``role``.

    False when ``role`` does not exist on this cluster. See MEMBER_OF_SQL.
    """
    cur.execute(MEMBER_OF_SQL, [role])
    return cur.fetchone()[0]


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

    * the seed genuinely has none -> fix ``seed/corpus.py``;
    * the owner is being filtered by the policies it created -> fix
      ``sql/11_roles_rls.sql``.

    The second is the dangerous one. Every derived projection is written by this
    identity, so a filtered owner silently truncates ``retrieval.documents`` and
    ``retrieval.chunks`` while reporting success (measured on PG17: 1 of 2 rows
    copied, exit 0). The row-filtering assertions below would then be true and
    meaningless. A superuser or ``BYPASSRLS`` owner cannot be in that state, which
    is what makes the first branch safe to attribute to the seed.
    """
    if exposure["is_super"] or exposure["bypasses_rls"]:
        return (
            f"the seed holds no restricted evidence. {exposure['owner']} bypasses "
            f"RLS (rolsuper={exposure['is_super']}, "
            f"rolbypassrls={exposure['bypasses_rls']}), so it read the table "
            f"unfiltered and the absence is real: reseed with seed/corpus.py's "
            f"RESTRICTED_ACL cohort"
        )
    unlisted = [t for t in READ_PATH_TABLES if t not in exposure["listed_on"]]
    if unlisted:
        return (
            f"{exposure['owner']} is not named by the policy on "
            f"{', '.join(unlisted)} and is subject to FORCE, so it sees ZERO rows "
            f"there -- this measurement is of a table the owner cannot read, not of "
            f"the seed. Add CURRENT_USER to those policies' TO lists "
            f"(sql/11_roles_rls.sql; Task 12 Step 3)"
        )
    if not exposure["has_clearance"]:
        return (
            f"{exposure['owner']} is named by every policy but does NOT hold "
            f"{CLEARANCE_GROUP}, so it reads workshop rows only. The restricted "
            f"cohort exists and is invisible to the identity that writes every "
            f"derived projection. Restore the "
            f"GRANT {CLEARANCE_GROUP} TO current_user block in sql/11_roles_rls.sql"
        )
    return (
        f"{exposure['owner']} is named by every policy and holds "
        f"{CLEARANCE_GROUP}, so it is reading unfiltered: the seed holds no "
        f"restricted evidence. Reseed with seed/corpus.py's RESTRICTED_ACL cohort"
    )


def run() -> int:  # noqa: C901 - four independent assertion groups, read top to bottom
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
        with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                present = _roles_present(cur, PERSONA_ROLES + (CLEARANCE_GROUP,))
                missing = sorted(
                    set(PERSONA_ROLES + (CLEARANCE_GROUP,)) - set(present)
                )
                if missing:
                    return finish(
                        GATE_ID,
                        BLOCKED,
                        f"roles not created yet: {', '.join(missing)}",
                    )
                state = _rls_state(cur)
                exposure = _owner_exposure(cur)
                cur.execute(RESTRICTED_KEYS_SQL)
                rows = cur.fetchall()
                restricted = [row[0] for row in rows]
                restricted_ids = [row[1] for row in rows]
                projected = {}
                for table in DERIVED_TABLES:
                    cur.execute(PROJECTED_RESTRICTED_SQL.format(table=table))
                    projected[table] = cur.fetchone()[0]
                # Measured here, in the owner connection, for the same reason
                # `projected` is: group (b') runs on the app connection under
                # SET LOCAL ROLE, where every count is by definition filtered.
                detail_restricted = {}
                for table in DETAIL_TABLES:
                    cur.execute(
                        DETAIL_RESTRICTED_COUNT_SQL.format(table=table),
                        [restricted_ids],
                    )
                    detail_restricted[table] = cur.fetchone()[0]
                junction_restricted = {}
                for table, near, far in JUNCTION_TABLES:
                    cur.execute(
                        JUNCTION_RESTRICTED_SQL.format(
                            table=table, near=near, far=far
                        ),
                        [restricted_ids, restricted_ids],
                    )
                    junction_restricted[table] = cur.fetchone()[0]
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    print("\n  RLS state (relrowsecurity / relforcerowsecurity):")
    for table in READ_PATH_TABLES:
        enabled, forced = state.get(table, (None, None))
        print(f"    {table}: enabled={enabled} forced={forced}")
    # Both tuples: a detail table without ENABLE+FORCE is the bypass this gate's
    # (b') group exists to catch, and reporting it as BLOCKED here names the
    # missing DDL instead of failing later with a confusing row count.
    unprotected = [
        table
        for table in READ_PATH_TABLES + DETAIL_TABLES + _junction_names()
        if state.get(table) != (True, True)
    ]
    if unprotected:
        return finish(
            GATE_ID,
            BLOCKED,
            f"RLS not enabled+forced yet on: {', '.join(unprotected)}",
        )

    # Everything below was measured as the owner, so print what the owner could
    # actually see while measuring it. Without this line a zero count reads as "the
    # seed has no restricted evidence" when the truth may be "the writer is blind".
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
    require(
        CANONICAL_RESTRICTED_KEY in restricted,
        f"{CANONICAL_RESTRICTED_KEY} is not restricted; M3's flip noun is broken",
    )

    # The projection must carry the restricted rows too, and this is NOT redundant
    # with (b). A non-superuser owner that is subject to FORCE but holds no clearance
    # reads a silently truncated source: the search-index build then projects only
    # workshop rows, and (b) below reports "analyst sees 0 restricted rows" -- a PASS
    # for the wrong reason, because there is nothing there to filter. Measured on
    # PG17: that configuration copied 1 of 2 rows and reported success. Assert the
    # restricted cohort SURVIVED into both derived tables before proving it is hidden.
    #
    # Counted with count(*) over is_current, not over external_key: retrieval.chunks
    # has no external_key column (sql/01_schema.sql:951-999) -- the key lives on
    # retrieval.documents (:895) and on casework.evidence_items (:34).
    print("\n  current restricted rows in the derived projection:")
    for table in DERIVED_TABLES:
        print(f"    {table}: {projected[table]}")
        require(
            projected[table] > 0,
            f"{table} holds no current restricted rows while "
            f"casework.evidence_items holds {len(restricted)}. The projection is "
            f"written by {exposure['owner']}, so either the search index has not "
            f"been rebuilt since the reseed, or that identity could not see the "
            f"restricted rows when it built it (named by "
            f"{len(exposure['listed_on'])}/{len(READ_PATH_TABLES)} policies, "
            f"{CLEARANCE_GROUP}={exposure['has_clearance']}) and truncated them "
            f"silently. Either way the row-filtering assertions below would hold "
            f"over an empty set",
        )

    # --- (a) fail-closed: the app login has no standing privilege path. ---
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
        with app_conn.cursor() as cur:
            cur.execute("SELECT current_user")
            login = cur.fetchone()[0]
            # Resolved through pg_roles: rds_superuser exists only on Aurora/RDS and
            # naming it inside pg_has_role() aborts the statement elsewhere. See
            # MEMBER_OF_SQL.
            is_master = _member_of(cur, "rds_superuser")
        print(f"    connected as: {login} (rds_superuser member: {is_master})")
        require(
            not is_master,
            f"{login} is an rds_superuser member; a cluster-master identity can "
            f"grant itself the clearance key at will, so the pool must not be one",
        )
        with app_conn.cursor() as cur:
            cur.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            require(
                cur.fetchone()[0] is False,
                f"{login} has BYPASSRLS; the pool identity must not",
            )
        for table in READ_PATH_TABLES:
            sqlstate = _denied_without_role(app_conn, table)
            print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
            require(
                sqlstate == "42501",
                f"bare SELECT on {table} as {login} did not raise permission denied "
                f"(got {sqlstate or 'success'}); the pool fails OPEN",
            )

        # --- (b) row filtering at the raw tables. ---
        # Probed by evidence_id, the only identity column on all three tables.
        print("\n  (b) row filtering at the raw tables:")
        for table in READ_PATH_TABLES:
            analyst = _ids_under_persona(
                app_conn, "persona_analyst", table, restricted_ids
            )
            admin = _ids_under_persona(
                app_conn, "persona_admin", table, restricted_ids
            )
            auditor = _ids_under_persona(
                app_conn, "persona_auditor", table, restricted_ids
            )
            print(
                f"    {table}: analyst={len(analyst)} admin={len(admin)} "
                f"auditor={len(auditor)} (of {len(restricted_ids)} restricted)"
            )
            require(
                analyst == set(),
                f"persona_analyst saw restricted rows at {table}: "
                f"{sorted(str(i) for i in analyst)}",
            )
            require(
                admin,
                f"persona_admin saw no restricted rows at {table}; the clearance "
                f"grant is missing",
            )
            require(
                auditor,
                f"persona_auditor saw no restricted rows at {table}; masking needs "
                f"the row present",
            )

        # --- (b') row filtering at the evidence detail tables. ---
        # The policies here clear through the parent, so this group measures a
        # DIFFERENT mechanism than (b): (b) proves the parent's predicate works,
        # this proves the children inherit it. A table holding no restricted
        # evidence is skipped rather than asserted on -- runbooks, lock_evidence,
        # customer_commitments and postmortems hold none in the current cohort, and
        # asserting "admin sees restricted rows" there would fail for a reason that
        # has nothing to do with RLS. The skip is driven by the OWNER's count, never
        # by persona_admin's: admin's own empty view cannot tell "this kind has no
        # restricted rows" apart from "admin's visibility is broken", and those two
        # need opposite verdicts. The analyst assertion runs on every table
        # regardless, because "the analyst sees nothing" holds either way.
        # The oracle above is only as good as the owner's own reach into these
        # tables, and _owner_exposure measures listed_on over READ_PATH_TABLES
        # only -- it says nothing about the seven detail tables. If section 5's
        # generated TO lists lost CURRENT_USER, or make schema ran as a different
        # identity than this gate's owner DSN, the owner is subject to FORCE and
        # reads ZERO rows here: all seven counts come back 0, all seven tables
        # take the skip branch, and the group reports clean over policies that
        # deny every persona. Measured on PG17 -- the same configuration that
        # silently truncated a derived projection to 1 of 2 rows at exit 0.
        #
        # casework.support_cases is the positive control the cohort guarantees:
        # seed/corpus.py:445-471 pins CANONICAL_RESTRICTED_KEY into it with
        # RESTRICTED_ACL, run() has already asserted that key is restricted, and
        # G-29's masking gate reads that exact row. A zero count there is never a
        # cohort property.
        print("\n  owner reach into the detail tables (oracle sanity):")
        for table in DETAIL_TABLES:
            print(f"    {table}: {detail_restricted[table]} restricted")
        require(
            detail_restricted[CONTROL_DETAIL_TABLE] > 0,
            f"the owner measured 0 restricted rows at {CONTROL_DETAIL_TABLE} while "
            f"casework.evidence_items holds {len(restricted)} including "
            f"{CANONICAL_RESTRICTED_KEY}, which seed/corpus.py pins into that table. "
            f"The owner is being filtered by the section 5 policies it created, so "
            f"every count below is 0 and every table would skip with a false "
            f"'no restricted evidence of this kind'. Check that section 5's "
            f"generated TO lists still include CURRENT_USER and that make schema "
            f"ran as the same identity this gate connects as "
            f"(sql/11_roles_rls.sql section 5)",
        )
        print("\n  (b') row filtering at the evidence detail tables:")
        for table in DETAIL_TABLES:
            analyst = _ids_under_persona(
                app_conn, "persona_analyst", table, restricted_ids
            )
            admin = _ids_under_persona(
                app_conn, "persona_admin", table, restricted_ids
            )
            auditor = _ids_under_persona(
                app_conn, "persona_auditor", table, restricted_ids
            )
            print(
                f"    {table}: analyst={len(analyst)} admin={len(admin)} "
                f"auditor={len(auditor)}"
            )
            require(
                analyst == set(),
                f"persona_analyst read restricted rows out of {table}: "
                f"{sorted(str(i) for i in analyst)}. RLS on the three read-path "
                f"tables does not cover the detail tables, and section 2 of "
                f"sql/11_roles_rls.sql grants every persona SELECT ON ALL TABLES "
                f"IN SCHEMA casework -- so the analyst is denied at "
                f"casework.evidence_items and then reads the same evidence body "
                f"here. Add the EXISTS-on-parent policy for this table "
                f"(sql/11_roles_rls.sql section 5)",
            )
            # The OWNER's count decides whether to skip, not persona_admin's. An
            # empty admin view is the failure this group exists to catch when the
            # rows are actually there, and a legitimate skip when they are not --
            # persona_admin cannot distinguish those two states about itself.
            if detail_restricted[table] == 0:
                print("      (no restricted evidence of this kind; analyst-only check)")
                continue
            require(
                admin,
                f"persona_admin saw none of the {detail_restricted[table]} restricted "
                f"rows the owner measured at {table}. Either persona_admin is missing "
                f"from that table's policy TO list or the EXISTS predicate is wrong "
                f"(sql/11_roles_rls.sql section 5). Without this assertion the gate "
                f"would have skipped the auditor check and reported PASS over a "
                f"policy that denies every persona",
            )
            require(
                auditor,
                f"persona_auditor saw no restricted rows at {table} while "
                f"persona_admin saw {len(admin)}; masking needs the row present",
            )

        # --- (b'') row filtering at the relation junction tables. ---
        # A third mechanism, not a repeat of (b'). The detail policies clear through
        # ONE parent; these clear through BOTH endpoints, because a junction row is
        # only visible if the caller can see both things it relates. Checking the
        # near side alone reproduces the measured leak: INC-2047 is workshop, so an
        # analyst who could see the near endpoint read
        # "The restricted case references the same cluster and interval." out of the
        # edge to a restricted case.
        #
        # Counted, not probed by id: these tables have no evidence_id column, and
        # the interesting row is the PAIR. The analyst assertion is exact equality
        # to 0 rather than a subset check, since every row counted here touches
        # restricted evidence on at least one side by construction.
        print("\n  owner reach into the junction tables (oracle sanity):")
        for table, _near, _far in JUNCTION_TABLES:
            print(f"    {table}: {junction_restricted[table]} touching restricted")
        print("\n  (b'') row filtering at the relation junction tables:")
        for table, near, far in JUNCTION_TABLES:
            analyst = _junction_rows_under_persona(
                app_conn, "persona_analyst", table, near, far, restricted_ids
            )
            admin = _junction_rows_under_persona(
                app_conn, "persona_admin", table, near, far, restricted_ids
            )
            auditor = _junction_rows_under_persona(
                app_conn, "persona_auditor", table, near, far, restricted_ids
            )
            print(
                f"    {table}: analyst={analyst} admin={admin} auditor={auditor} "
                f"(owner={junction_restricted[table]})"
            )
            require(
                analyst == 0,
                f"persona_analyst read {analyst} junction rows touching restricted "
                f"evidence out of {table}. The rationale on those rows names the "
                f"relationship the ACL withholds, and retrieval.evidence_edges "
                f"reads this table, so /v1/evidence/{{id}} leaks it too. RLS is "
                f"enabled+forced here (asserted above), so the policy exists but "
                f"its predicate is too weak: check that it requires BOTH endpoint "
                f"columns ({near} AND {far}) to resolve in casework.evidence_items "
                f"-- a near-side-only EXISTS passes every row whose visible "
                f"endpoint the analyst can already see "
                f"(sql/11_roles_rls.sql section 6)",
            )
            if junction_restricted[table] == 0:
                print("      (relates no restricted evidence; analyst-only check)")
                continue
            require(
                admin == junction_restricted[table],
                f"persona_admin read {admin} of the {junction_restricted[table]} "
                f"junction rows the owner measured at {table}. Either persona_admin "
                f"is missing from that table's policy TO list or an endpoint column "
                f"in the both-endpoints predicate is wrong "
                f"(sql/11_roles_rls.sql section 6)",
            )
            require(
                auditor == junction_restricted[table],
                f"persona_auditor read {auditor} of the "
                f"{junction_restricted[table]} junction rows at {table} while "
                f"persona_admin read {admin}; the two personas hold the same "
                f"clearance and differ only in masking, which does not apply here",
            )

        # --- (c) replay determinism + transaction scope. ---
        print("\n  (c) replay determinism and transaction scope:")
        first = _ids_under_persona(
            app_conn, "persona_admin", READ_PATH_TABLES[0], restricted_ids
        )
        second = _ids_under_persona(
            app_conn, "persona_admin", READ_PATH_TABLES[0], restricted_ids
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

    return finish(
        GATE_ID,
        PASS,
        f"fail-closed on {len(READ_PATH_TABLES)} tables; {len(restricted)} restricted "
        f"rows hidden from analyst across {len(DETAIL_TABLES)} detail and "
        f"{len(JUNCTION_TABLES)} junction tables, visible to admin+auditor; "
        f"replay deterministic",
    )


if __name__ == "__main__":
    main_guard(run)
