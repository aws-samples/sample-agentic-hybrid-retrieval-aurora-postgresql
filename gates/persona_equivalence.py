#!/usr/bin/env python3
"""G-31 - Persona equivalence: the security module changes policy, not contract.

sql/11_roles_rls.sql section 1 makes a specific promise when it upgrades
``retrieval.acl_visible`` to consult the clearance group: the security module
changes *who can see what* without changing the retrieval contract. An uncleared
persona must retrieve exactly the rows the core, security-off rule would have
returned, and a cleared persona must retrieve exactly what the schema owner reads.
That is the claim this gate holds the live database to.

Three assertions, one per read-path table:

1. ``persona_app_engineer`` under a **bare SELECT** returns exactly the row set the
   core rule selects: ``coalesce(acl->>'visibility','restricted') = 'workshop'``
   (sql/03_search_functions.sql:1-30). Not the same count -- the same primary keys.
2. ``persona_dba`` and ``persona_auditor`` under a bare SELECT return exactly the
   owner's unfiltered row set, because both hold ``can_see_restricted``.
3. The two sets differ. Equivalence between an uncleared and a cleared persona means
   the clearance does nothing, which would satisfy (1) and (2) only on a corpus with
   no restricted rows -- where this gate has nothing to say and says so.

**The asymmetry between the two sides is the assertion.** The expected side applies
the core rule explicitly, as the schema owner. The measured side applies NO
predicate at all: it issues a bare SELECT under the persona and lets RLS do the
filtering. Any other shape is vacuous. Filter both sides on visibility and the
gate passes with every row policy dropped, because the explicit WHERE performs the
filtering the policies were supposed to prove.

Every read is single-table, and that is load-bearing rather than tidy. All three
read-path tables carry their own row policy, so a query that reaches one table
through another lets the second table's policy supply the filtering and the gate
reports a protection that the table under test is not providing. Measured on this
cluster while building G-29: with ``retrieval.chunks``' policy loosened to
``USING (true)``, a bare SELECT read every chunk while the same query joined to
``retrieval.documents`` still omitted restricted chunks -- green on a schema that
had handed the uncleared persona every restricted chunk.

**No committed baseline.** An earlier design compared against a JSON file captured
before the vocabulary collapse. That file cannot honestly exist here: the
pre-collapse corpus is gone, the two-jsonb ``retrieval.acl_visible(jsonb, jsonb)``
it replayed is dropped at sql/03_search_functions.sql:2, and the participant path
is live-data-only, so shipping an authored expectation would be the substitution
the project forbids. The core rule is still in the tree and still executable, so
the expectation is *computed* from it on every run instead. It cannot go stale, and
it still fails if a policy is dropped, mis-scoped, or created without FORCE.

Read-only: SELECT, ``SET LOCAL ROLE``, ROLLBACK.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-31"
TITLE = "Persona equivalence: policy changes, contract does not"

UNCLEARED = "persona_app_engineer"
CLEARED = ("persona_dba", "persona_auditor")
CLEARANCE_GROUP = "can_see_restricted"

# The core, security-off visibility rule, restated in SQL rather than called.
#
# Calling retrieval.acl_visible() here would be circular: sql/11 section 1 REPLACES
# that function with one that consults can_see_restricted, so under a cleared
# persona the "expected" side would return the same rows as the measured side by
# construction and assertion (2) would hold vacuously. The rule is stable and one
# line long (sql/03_search_functions.sql:1-30) -- restating it is what keeps the
# comparison honest. Its fail-closed default is part of the rule: an absent or
# null visibility reads as 'restricted', never as visible.
CORE_RULE = "coalesce({column} ->> 'visibility', 'restricted') = 'workshop'"

# The three protected read-path tables, with the primary key each comparison is
# keyed on and the jsonb column carrying the authoritative classification.
#
# Keyed on identity, not on count. Two row sets of equal size can still differ, and
# a policy that swapped which rows it admitted would be invisible to a count.
READ_PATH = (
    {"table": "casework.evidence_items", "key": "evidence_id", "acl": "acl"},
    {"table": "retrieval.documents", "key": "document_version_id", "acl": "acl"},
    {"table": "retrieval.chunks", "key": "chunk_version_id", "acl": "acl"},
)

ROLES_SQL = "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)"

# FORCE, not merely ENABLE. relrowsecurity alone leaves the table owner exempt, and
# the personas are not the owner -- but the owner exemption is what would let a
# future pool connect as retrieval_admin and read everything, so sql/11 forces it.
PROTECTION_SQL = """
SELECT c.relrowsecurity, c.relforcerowsecurity
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname || '.' || c.relname = %s
"""


def _bare_select(table: str, key: str) -> str:
    """Return an unfiltered keyed row set from one table.

    No predicate beyond the key ordering: RLS is the subject under test, so any
    visibility filter here would perform the work the policy is supposed to do.
    """
    return f"SELECT {key}::text FROM {table} ORDER BY 1"


def _expected_select(table: str, key: str, acl: str) -> str:
    """Return the keyed row set the core security-off rule admits."""
    return (
        f"SELECT {key}::text FROM {table} "
        f"WHERE {CORE_RULE.format(column=acl)} ORDER BY 1"
    )


def _fetch(conn, statement: str, persona: str | None = None) -> list[str]:
    """Run one read-only SELECT, optionally under ``persona``, and roll back."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            if persona:
                cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(statement)
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.execute("ROLLBACK")


def _measure_as_owner(psycopg, owner_dsn: str) -> dict | str:
    """Measure protection flags plus the unfiltered and core-rule row sets.

    Returns:
        Per-table measurements, or a BLOCKED reason string.
    """
    measured = {}
    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            wanted = [UNCLEARED, *CLEARED, CLEARANCE_GROUP]
            cur.execute(ROLES_SQL, [wanted])
            missing = sorted(set(wanted) - {row[0] for row in cur.fetchall()})
            if missing:
                return f"roles not created yet: {', '.join(missing)}"

        for entry in READ_PATH:
            table, key = entry["table"], entry["key"]
            with conn.cursor() as cur:
                cur.execute(PROTECTION_SQL, [table])
                flags = cur.fetchone()
            if flags is None:
                return f"{table} does not exist yet"
            measured[table] = {
                "enabled": flags[0],
                "forced": flags[1],
                # Unfiltered, as the owner: RLS is FORCEd, so the owner is subject
                # to its own policies and this read would be filtered too. The
                # policy admits retrieval_admin through the clearance disjunct
                # (sql/11 grants it can_see_restricted so the index build can
                # index the whole corpus), which is why this is the cleared
                # personas' expectation rather than a bypass.
                "unfiltered": _fetch(conn, _bare_select(table, key)),
                "core_rule": _fetch(conn, _expected_select(table, key, entry["acl"])),
            }
    return measured


def _assert_protection(measured: dict) -> None:
    """Assert every read-path table has RLS enabled AND forced."""
    print("\n  (0) protection - RLS enabled and FORCEd on the read path:")
    for entry in READ_PATH:
        table = entry["table"]
        flags = measured[table]
        print(
            f"    {table}: enabled={flags['enabled']} forced={flags['forced']} "
            f"({len(flags['unfiltered'])} rows owner-visible, "
            f"{len(flags['core_rule'])} admitted by the core rule)"
        )
        require(
            flags["enabled"] and flags["forced"],
            f"{table} has RLS enabled={flags['enabled']} forced={flags['forced']}. "
            f"Without FORCE the table owner is exempt from its own policies, so this "
            f"gate's owner-side measurement would silently become an unfiltered read "
            f"of a table nobody is protecting (sql/11_roles_rls.sql sections 4-5)",
        )


def _assert_non_vacuous(measured: dict) -> None:
    """Assert the corpus actually contains restricted rows on every table.

    Without this the whole gate holds trivially: if nothing is restricted, the core
    rule admits everything, the uncleared persona reads everything, and all three
    assertions pass on a database with no security to test.
    """
    print("\n  (1) non-vacuity - the corpus contains restricted rows:")
    for entry in READ_PATH:
        table = entry["table"]
        hidden = len(measured[table]["unfiltered"]) - len(measured[table]["core_rule"])
        print(f"    {table}: {hidden} row(s) the core rule excludes")
        require(
            hidden > 0,
            f"every row in {table} is workshop-visible, so the core rule admits all "
            f"of them and this gate would PASS without exercising a single policy. "
            f"The capture has no restricted evidence yet: run make live-workshop "
            f"before trusting this verdict",
        )


def _assert_uncleared_matches_core(app_conn, measured: dict) -> None:
    """Assert the uncleared persona's bare SELECT equals the core rule's row set."""
    print(f"\n  (2) {UNCLEARED} bare SELECT == the core security-off rule:")
    for entry in READ_PATH:
        table, key = entry["table"], entry["key"]
        actual = _fetch(app_conn, _bare_select(table, key), UNCLEARED)
        expected = measured[table]["core_rule"]
        print(f"    {table}: persona={len(actual)} core rule={len(expected)}")
        require(
            actual == expected,
            f"{UNCLEARED} read {len(actual)} rows from {table} where the core rule "
            f"admits {len(expected)}, and the sets are not identical "
            f"({len(set(actual) - set(expected))} extra, "
            f"{len(set(expected) - set(actual))} missing). RLS is supposed to "
            f"reproduce the retrieval contract exactly: extra rows mean the security "
            f"module widened what an uncleared identity retrieves, missing rows mean "
            f"it removed evidence the workshop depends on. Either way sql/11 section "
            f"1's promise -- policy changes, contract does not -- is false",
        )


def _assert_cleared_matches_owner(app_conn, measured: dict) -> None:
    """Assert each cleared persona's bare SELECT equals the owner's row set."""
    print(f"\n  (3) cleared personas == unfiltered, and differ from {UNCLEARED}:")
    for persona in CLEARED:
        for entry in READ_PATH:
            table, key = entry["table"], entry["key"]
            actual = _fetch(app_conn, _bare_select(table, key), persona)
            expected = measured[table]["unfiltered"]
            print(f"    {persona} {table}: {len(actual)} of {len(expected)}")
            require(
                actual == expected,
                f"{persona} holds {CLEARANCE_GROUP} but read {len(actual)} of the "
                f"{len(expected)} rows in {table}. A cleared persona that cannot "
                f"reach restricted evidence cannot do the job the lab gives it, and "
                f"the clearance disjunct in the row policy is not firing "
                f"(sql/11_roles_rls.sql sections 4-5)",
            )
            require(
                len(actual) > len(measured[table]["core_rule"]),
                f"{persona} reads the same {len(actual)} rows from {table} that the "
                f"uncleared core rule admits, so {CLEARANCE_GROUP} grants nothing "
                f"and the two personas are indistinguishable. The membership exists "
                f"but the policy is not consulting it",
            )


def run() -> int:
    print_header(GATE_ID, TITLE)

    owner_dsn = read_env_value("DATABASE_URL")
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not owner_dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")
    if not app_dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_APP_DATABASE_URL is not set; cannot SET LOCAL ROLE as the pool",
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(owner_dsn)}")

    try:
        measured = _measure_as_owner(psycopg, owner_dsn)
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")
    if isinstance(measured, str):
        return finish(GATE_ID, BLOCKED, measured)

    _assert_protection(measured)
    _assert_non_vacuous(measured)

    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app_conn:
        # A persona the pool cannot assume, or a missing SELECT grant, is an unbuilt
        # sql/11 dependency rather than semantic drift. main_guard translates only
        # AssertionError, so an escaping InsufficientPrivilege would be a traceback
        # where the contract wants an honest BLOCKED -- and FAILing would claim the
        # security module altered the retrieval contract when nothing is wired yet.
        try:
            _assert_uncleared_matches_core(app_conn, measured)
            _assert_cleared_matches_owner(app_conn, measured)
        except psycopg.errors.InsufficientPrivilege as exc:
            return finish(
                GATE_ID,
                BLOCKED,
                f"a persona cannot be assumed or cannot read the corpus: {exc}",
            )
        except psycopg.errors.InvalidObjectDefinition as exc:
            # A policy whose USING clause queries the table it protects raises
            # "infinite recursion detected in policy" (42P17) on every persona read
            # while the owner's own measurement succeeds, because the owner reaches
            # the rows through the clearance disjunct before the subquery re-enters.
            # That is a broken policy, so it is a FAIL, not BLOCKED -- but it is not
            # an AssertionError, so without this catch main_guard prints a traceback
            # and the exit code lands on FAIL for the wrong reason. Measured while
            # building this gate's regression set.
            return finish(
                GATE_ID,
                FAIL,
                f"a read-path row policy is not evaluable by a persona: {exc}. A "
                f"USING clause that selects from the table it protects recurses; "
                f"reach the classification through the row's own denormalized "
                f"column instead (sql/11_roles_rls.sql sections 4-5)",
            )

    restricted = sum(
        len(measured[e["table"]]["unfiltered"]) - len(measured[e["table"]]["core_rule"])
        for e in READ_PATH
    )
    return finish(
        GATE_ID,
        PASS,
        f"across {len(READ_PATH)} FORCEd read-path tables holding {restricted} "
        f"restricted rows, {UNCLEARED} reproduces the core security-off rule's row "
        f"set identically under a bare SELECT, and {', '.join(CLEARED)} reproduce "
        f"the unfiltered set; the security module changed policy, not the contract",
    )


if __name__ == "__main__":
    main_guard(run)
