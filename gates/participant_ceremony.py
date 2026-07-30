#!/usr/bin/env python3
"""G-30 - Participant zero-ceremony identity (A1, 2026-07-28).

The Lab-1 terminal identity is ``workshop_participant``. Two claims:

1. Zero ceremony. Every statement a Lab-1 snippet issues runs as-is under this
   identity: the monitoring views (``pg_stat_activity``, ``pg_locks``,
   ``pg_stat_progress_create_index``) are readable, the exercise schema is readable,
   and ``casework.admit_evidence`` is EXECUTE-able. No ``SET ROLE`` first, no grant
   step, no sudo. If a participant has to type anything the guide does not show, the
   guide is wrong.

2. Fail-closed first lesson. A bare ``SELECT`` on ``casework.evidence_items`` /
   ``retrieval.documents`` / ``retrieval.chunks`` from the same identity raises
   ``permission denied`` (SQLSTATE 42501). Evidence reads require assuming a persona;
   the denial is the lesson, not a bug.

Monitoring-view caveat asserted explicitly: without ``pg_monitor`` membership,
``pg_stat_activity`` silently shows only the participant's OWN backend rows. The
gate asserts membership rather than merely that the view is selectable, because
"selectable but empty" is the failure mode that survives a naive check.

Read-only: SELECT and catalog reads only. ``casework.admit_evidence`` is probed for
EXECUTE privilege via ``has_function_privilege``, never actually invoked - the gate
contract forbids writes.
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

GATE_ID = "G-30"
TITLE = "Participant zero-ceremony identity (A1)"

PARTICIPANT_ROLE = "workshop_participant"
PERSONA_ROLES = ("persona_analyst", "persona_admin", "persona_auditor")

# Monitoring reads every Lab-1 watch.sql snippet performs.
MONITORING_VIEWS = (
    "pg_stat_activity",
    "pg_locks",
    "pg_stat_progress_create_index",
)

DENIED_TABLES = (
    "casework.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)

ADMIT_FUNCTION = "casework.admit_evidence(jsonb)"


def _probe_select(conn, statement: str) -> str | None:
    """Return the SQLSTATE raised by ``statement``, or None when it succeeded."""
    import psycopg

    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(statement)
            cur.fetchall()
            return None
        except psycopg.errors.InsufficientPrivilege as exc:
            return exc.sqlstate
        finally:
            cur.execute("ROLLBACK")


def run() -> int:  # noqa: C901 - four assertion groups, read top to bottom
    print_header(GATE_ID, TITLE)

    dsn = read_env_value("WORKSHOP_PARTICIPANT_DATABASE_URL")
    if not dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_PARTICIPANT_DATABASE_URL is not set; the participant identity "
            "is provisioned by the sibling Workshop Studio repo",
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(dsn)}")

    try:
        with psycopg.connect(dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user")
                login = cur.fetchone()[0]
            print(f"    connected as: {login}")
            if login != PARTICIPANT_ROLE:
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"connected as {login}, expected {PARTICIPANT_ROLE}",
                )

            print("\n  (1a) monitoring visibility - pg_monitor membership:")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_has_role(current_user, 'pg_monitor', 'USAGE')"
                )
                is_monitor = cur.fetchone()[0]
            print(f"    pg_monitor member: {is_monitor}")
            require(
                is_monitor,
                f"{login} is not a pg_monitor member; pg_stat_activity will show only "
                f"its own backend and every Lab-1 watch snippet reads as empty",
            )

            print("\n  (1b) zero-ceremony monitoring reads:")
            for view in MONITORING_VIEWS:
                sqlstate = _probe_select(conn, f"SELECT * FROM {view} LIMIT 1")
                print(f"    {view}: {sqlstate or 'readable'}")
                require(
                    sqlstate is None,
                    f"{login} cannot read {view} (sqlstate {sqlstate}); the Lab-1 "
                    f"snippet needs a grant the guide does not show",
                )

            # The catalog read comes FIRST, and its absence is BLOCKED rather than
            # FAIL. has_function_privilege() resolves its text argument to an OID
            # while the statement is planned, so it raises UndefinedFunction (42883)
            # on a cluster where sql/10 has not run -- a traceback, not a verdict,
            # exactly like the pg_has_role trap under (1d). Catalog read only; the
            # gate never invokes the writer.
            print("\n  (1c) admission function shape (catalog read):")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner)
                      FROM pg_proc p
                      JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'casework'
                       AND p.proname = 'admit_evidence'
                       AND pg_get_function_identity_arguments(p.oid) = 'payload jsonb'
                    """
                )
                row = cur.fetchone()
            if row is None:
                return finish(
                    GATE_ID, BLOCKED, f"{ADMIT_FUNCTION} does not exist yet"
                )
            secdef, proconfig, owner = row
            print(f"    prosecdef={secdef} owner={owner} proconfig={proconfig}")
            require(
                secdef,
                f"{ADMIT_FUNCTION} is not SECURITY DEFINER; its body runs as the "
                f"caller, so ./admit.sh raises permission denied on "
                f"casework.ingest_receipts for {login}",
            )
            has_search_path = any(
                entry.startswith("search_path=") for entry in (proconfig or [])
            )
            require(
                has_search_path,
                f"{ADMIT_FUNCTION} is SECURITY DEFINER with no pinned search_path; a "
                f"participant-controlled search_path is a privilege-escalation vector",
            )

            # EXECUTE is necessary and NOT sufficient, which is why it is checked
            # after the shape above and not instead of it: admit_evidence would run
            # with the CALLER's privileges without prosecdef, and its body reads and
            # writes five tables the participant holds no grant on, so ./admit.sh
            # would die on "permission denied for table ingest_receipts" while this
            # probe still reports true. Safe to run only now that the function is
            # known to exist -- the text argument resolves to an OID at plan time.
            print("\n  (1c') admission EXECUTE privilege (probed, never invoked):")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
                    [ADMIT_FUNCTION],
                )
                can_admit = cur.fetchone()[0]
            print(f"    {ADMIT_FUNCTION}: EXECUTE={can_admit}")
            require(
                can_admit,
                f"{login} cannot EXECUTE {ADMIT_FUNCTION}; ./admit.sh would fail",
            )

            # 'MEMBER', not 'USAGE' -- the one place in this plan where MEMBER is the
            # right mode. The question here is "can this login SET ROLE to the
            # persona?", and the grants are WITH INHERIT FALSE. Measured on PG17
            # against exactly that grant: USAGE reports false, MEMBER reports true,
            # and SET LOCAL ROLE succeeds. USAGE would fail this assertion on a
            # correctly-provisioned cluster. The policy expression still uses USAGE,
            # because it asks the opposite question -- whether privileges are
            # inherited passively -- and that is what withholding the key means.
            print("\n  (1d) persona roles grantable (SET ROLE available):")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    [list(PERSONA_ROLES)],
                )
                existing = {row[0] for row in cur.fetchall()}
            absent = [p for p in PERSONA_ROLES if p not in existing]
            if absent:
                # Not a FAIL, and not probed either: pg_has_role() raises
                # UndefinedObject on a missing role, which would turn this gate's
                # report into a traceback. BLOCKED is the honest answer for a subject
                # that has not been built.
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"persona roles not created yet: {', '.join(absent)}",
                )
            for persona in PERSONA_ROLES:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_has_role(current_user, %s, 'MEMBER')", [persona])
                    member = cur.fetchone()[0]
                print(f"    {persona}: grantable={member}")
                require(
                    member,
                    f"{login} is not granted {persona}; the psql persona coda cannot run",
                )

            print("\n  (2) fail-closed first lesson - bare SELECT on evidence:")
            for table in DENIED_TABLES:
                sqlstate = _probe_select(conn, f"SELECT 1 FROM {table} LIMIT 1")
                print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
                require(
                    sqlstate == "42501",
                    f"bare SELECT on {table} as {login} did not raise permission "
                    f"denied (got {sqlstate or 'success'}); the first lesson is gone",
                )
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    return finish(
        GATE_ID,
        PASS,
        f"{PARTICIPANT_ROLE} reads {len(MONITORING_VIEWS)} monitoring views with zero "
        f"ceremony, can EXECUTE admission, and is denied on all "
        f"{len(DENIED_TABLES)} evidence tables",
    )


if __name__ == "__main__":
    main_guard(run)
