#!/usr/bin/env python3
"""G-30 - Participant zero-ceremony identity (A1).

The Lab-1 terminal identity is ``workshop_participant``. Three claims:

1. **Zero ceremony.** Every statement a Lab-1 snippet issues runs as-is under this
   identity: the monitoring views (``pg_stat_activity``, ``pg_locks``,
   ``pg_stat_progress_create_index``) are readable and ``evidence.admit_evidence``
   is EXECUTE-able. No ``SET ROLE`` first, no grant step, no sudo. If a participant
   has to type anything the guide does not show, the guide is wrong.

2. **Fail-closed first lesson.** A bare ``SELECT`` on ``evidence.evidence_items`` /
   ``retrieval.documents`` / ``retrieval.chunks`` from the same identity raises
   ``permission denied`` (SQLSTATE 42501). Evidence reads require assuming a
   persona; the denial is the lesson, not a bug.

3. **Least privilege.** The login holds no SUPERUSER, no BYPASSRLS, no CREATEROLE
   and no CREATEDB. BYPASSRLS is the one that matters most: it would silently make
   every RLS assertion in G-27 vacuous for this identity, and it is exactly the
   attribute a frustrated operator reaches for when a participant hits a denial.

Two caveats are asserted rather than assumed, because both have a failure mode that
survives a naive check:

* **pg_monitor membership.** Without it ``pg_stat_activity`` is still SELECTable and
  simply shows only the participant's OWN backend. "Readable" is not the claim; the
  claim is that the lab's lock-contention snippet sees the blocking session.

* **SECURITY DEFINER shape of the admission function.** EXECUTE is necessary and not
  sufficient. ``evidence.admit_evidence`` writes tables the participant holds no
  grant on, so without ``prosecdef`` the EXECUTE probe reports true while
  ``./admit.sh`` dies on ``permission denied for table ingest_receipts``. The
  pinned ``search_path`` is asserted with it: a SECURITY DEFINER function with a
  caller-controlled search_path is a privilege-escalation vector.

Read-only: SELECT and catalog reads. ``evidence.admit_evidence`` is probed with
``has_function_privilege``, never invoked - the gate contract forbids writes, and
invoking it would write evidence into the participant's own capture.
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
PERSONA_ROLES = ("persona_app_engineer", "persona_dba", "persona_auditor")

# The monitoring reads every Lab-1 watch snippet performs.
MONITORING_VIEWS = (
    "pg_stat_activity",
    "pg_locks",
    "pg_stat_progress_create_index",
)

DENIED_TABLES = (
    "evidence.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)

ADMIT_FUNCTION = "evidence.admit_evidence(jsonb)"

# Attributes the participant login must not hold. rolbypassrls is the load-bearing
# one: with it, this identity reads every restricted row and G-27's entire subject
# disappears for the one login a participant actually types into.
FORBIDDEN_ATTRIBUTES = ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")

ATTRIBUTES_SQL = f"""
SELECT rolcanlogin, {', '.join(FORBIDDEN_ATTRIBUTES)}
  FROM pg_roles
 WHERE rolname = current_user
"""

# pg_get_function_identity_arguments includes PARAMETER NAMES: measured on this
# cluster it returns 'payload jsonb', not 'jsonb'. Comparing against 'jsonb' would
# match nothing and report the function absent on a healthy database.
ADMIT_SHAPE_SQL = """
SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner)
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'evidence'
   AND p.proname = 'admit_evidence'
   AND pg_get_function_identity_arguments(p.oid) = 'payload jsonb'
"""

ROLES_SQL = "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)"


def _probe_select(conn, statement: str) -> str | None:
    """Return the SQLSTATE ``statement`` raised, or None when it succeeded."""
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


def _assert_least_privilege(conn, login: str) -> None:
    """Assert the participant login can log in and holds no escalating attribute."""
    print("\n  (3) least privilege - login attributes:")
    with conn.cursor() as cur:
        cur.execute(ATTRIBUTES_SQL)
        row = cur.fetchone()
    can_login, attributes = row[0], dict(zip(FORBIDDEN_ATTRIBUTES, row[1:]))
    print(f"    rolcanlogin={can_login} " + " ".join(
        f"{name}={value}" for name, value in attributes.items()
    ))
    require(
        can_login,
        f"{login} cannot log in, yet this gate is connected as it; the role was "
        f"altered underneath a live session",
    )
    held = [name for name, value in attributes.items() if value]
    require(
        not held,
        f"{login} holds {', '.join(held)}. rolbypassrls in particular makes every "
        f"row policy sql/11_roles_rls.sql creates inert for the one identity a "
        f"participant types into, so G-27 would still PASS while this terminal read "
        f"every restricted row (sql/11_roles_rls.sql section 3 asserts this and "
        f"never ALTERs it)",
    )


def _assert_monitoring(conn, login: str) -> None:
    """Assert pg_monitor membership and that every Lab-1 monitoring read runs."""
    print("\n  (1a) monitoring visibility - pg_monitor membership:")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_has_role(current_user, 'pg_monitor', 'USAGE')")
        is_monitor = cur.fetchone()[0]
    print(f"    pg_monitor member: {is_monitor}")
    require(
        is_monitor,
        f"{login} is not a pg_monitor member. pg_stat_activity stays SELECTable and "
        f"silently narrows to this backend's own rows, so the lock-contention "
        f"snippet reads as empty and the lab's central observation never appears",
    )

    print("\n  (1b) zero-ceremony monitoring reads:")
    for view in MONITORING_VIEWS:
        sqlstate = _probe_select(conn, f"SELECT * FROM {view} LIMIT 1")
        print(f"    {view}: {sqlstate or 'readable'}")
        require(
            sqlstate is None,
            f"{login} cannot read {view} (sqlstate {sqlstate}); the Lab-1 snippet "
            f"needs a grant the guide does not show",
        )


def _assert_admission(conn, login: str) -> str | None:
    """Assert the admission function's shape, then its EXECUTE grant.

    Returns:
        A BLOCKED reason when the function does not exist yet, else None.
    """
    print("\n  (1c) admission function shape (catalog read):")
    with conn.cursor() as cur:
        cur.execute(ADMIT_SHAPE_SQL)
        row = cur.fetchone()
    if row is None:
        return f"{ADMIT_FUNCTION} does not exist yet"
    secdef, proconfig, owner = row
    print(f"    prosecdef={secdef} owner={owner} proconfig={proconfig}")
    require(
        secdef,
        f"{ADMIT_FUNCTION} is not SECURITY DEFINER, so its body runs with the "
        f"caller's privileges and ./admit.sh raises permission denied on "
        f"evidence.ingest_receipts for {login}",
    )
    require(
        any(entry.startswith("search_path=") for entry in (proconfig or [])),
        f"{ADMIT_FUNCTION} is SECURITY DEFINER with no pinned search_path; a "
        f"participant-controlled search_path resolves its unqualified names and "
        f"turns the function into a privilege-escalation vector",
    )

    # Checked AFTER the shape, and deliberately not instead of it. The shape probe
    # also has to come first mechanically: has_function_privilege resolves its text
    # argument to an OID at plan time, so it raises UndefinedFunction on a cluster
    # where the function is absent -- a traceback where the contract wants BLOCKED.
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
        f"{login} cannot EXECUTE {ADMIT_FUNCTION}; ./admit.sh fails at the step the "
        f"guide presents as a single command",
    )
    return None


def _assert_personas_grantable(conn, login: str) -> str | None:
    """Assert the login can SET ROLE to each persona.

    Returns:
        A BLOCKED reason when a persona has not been created yet, else None.
    """
    print("\n  (1d) persona roles grantable (SET ROLE available):")
    with conn.cursor() as cur:
        cur.execute(ROLES_SQL, [list(PERSONA_ROLES)])
        existing = {row[0] for row in cur.fetchall()}
    absent = [p for p in PERSONA_ROLES if p not in existing]
    if absent:
        # Not FAIL, and not probed either: pg_has_role raises UndefinedObject on a
        # missing role, which would turn this gate's report into a traceback.
        return f"persona roles not created yet: {', '.join(absent)}"

    # 'MEMBER', not 'USAGE'. The question here is "can this login SET ROLE to the
    # persona?", and sql/11 makes those grants WITH INHERIT FALSE. Measured against
    # exactly that grant: USAGE reports false, MEMBER reports true, and SET LOCAL
    # ROLE succeeds -- so USAGE would fail this assertion on a correct cluster. The
    # row policies still use USAGE, because they ask the opposite question (are
    # privileges inherited passively), and withholding inheritance is the point.
    for persona in PERSONA_ROLES:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_has_role(current_user, %s, 'MEMBER')", [persona])
            member = cur.fetchone()[0]
        print(f"    {persona}: grantable={member}")
        require(
            member,
            f"{login} is not granted {persona}, so the psql persona coda the lab "
            f"ends on cannot run",
        )
    return None


def _assert_fail_closed(conn, login: str) -> None:
    """Assert a bare SELECT on each evidence table is denied outright."""
    print("\n  (2) fail-closed first lesson - bare SELECT on evidence:")
    for table in DENIED_TABLES:
        sqlstate = _probe_select(conn, f"SELECT 1 FROM {table} LIMIT 1")
        print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
        require(
            sqlstate == "42501",
            f"a bare SELECT on {table} as {login} did not raise permission denied "
            f"(got {sqlstate or 'success'}). The first lesson is that evidence reads "
            f"require assuming a persona; without the denial there is nothing to "
            f"teach and no ceremony to justify",
        )


def run() -> int:
    print_header(GATE_ID, TITLE)

    dsn = read_env_value("WORKSHOP_PARTICIPANT_DATABASE_URL")
    if not dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_PARTICIPANT_DATABASE_URL is not set; the participant identity "
            "is provisioned by the sibling Workshop Studio repo and this gate "
            "asserts what that login can do, which cannot be probed as anyone else",
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
                    f"connected as {login}, expected {PARTICIPANT_ROLE}; every claim "
                    f"below is about one specific login and cannot be probed by "
                    f"proxy",
                )

            _assert_monitoring(conn, login)
            blocked = _assert_admission(conn, login)
            if blocked:
                return finish(GATE_ID, BLOCKED, blocked)
            blocked = _assert_personas_grantable(conn, login)
            if blocked:
                return finish(GATE_ID, BLOCKED, blocked)
            _assert_fail_closed(conn, login)
            _assert_least_privilege(conn, login)
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    return finish(
        GATE_ID,
        PASS,
        f"{PARTICIPANT_ROLE} is a pg_monitor member that reads "
        f"{len(MONITORING_VIEWS)} monitoring views with zero ceremony, can EXECUTE "
        f"the SECURITY DEFINER admission function with a pinned search_path, can "
        f"assume all {len(PERSONA_ROLES)} personas, is denied on all "
        f"{len(DENIED_TABLES)} evidence tables, and holds none of "
        f"{', '.join(FORBIDDEN_ATTRIBUTES)}",
    )


if __name__ == "__main__":
    main_guard(run)
