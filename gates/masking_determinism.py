#!/usr/bin/env python3
"""G-29 - Column masking and Law-2 determinism (A3/A5, D24).

RLS decides which ROWS a persona reads; masking decides which COLUMNS it reads
inside a row it is allowed to see. This gate asserts the second half, on the
tables sql/12_masking.sql actually names, against the literals the participant's
own capture produced.

Four assertions:

1. **Masking is real, per policy, per column.** Every masking policy is read from
   ``pgcolumnmask.ddm_policies`` and each masked column is compared against the
   OWNER's stored value: a role the policy names must differ from it, a role it
   does not name must equal it byte for byte. Both halves are needed. Comparing
   two persona views to each other cannot tell "dba is raw" from "dba is masked
   differently", and asserting only that the masked role differs would pass on a
   policy that redacts the unmasked baseline too - which destroys the comparison
   the lab asks a participant to run.

2. **Law 2 determinism.** The same SELECT under the same persona in two separate
   transactions returns byte-identical values. That is what lets a panel and its
   pasted ``_verify_sql`` agree: both run the identical masked expression. The
   mask functions are IMMUTABLE for this reason (sql/12 section 1).

3. **A5 pattern provenance.** The sensitive literals come from
   ``retrieval.sensitive_literals()`` - the resolved statement text of the
   restricted rows in the CURRENT capture - never from a list in this file. If the
   participant's run captures different statements, the gate's expectations follow.

4. **A5 leak scan over what the persona can actually read.** Every literal is
   searched for across each masked table's masked columns AND across the current
   chunk corpus, in the persona's own result set.

The scan is CLIENT-SIDE, and that is forced rather than chosen. ``pg_columnmask``
refuses any predicate touching a masked column, so a server-side
``WHERE query ILIKE ...`` raises ``FeatureNotSupported`` for exactly the roles
whose masking is under test - measured: the scan errored for app_engineer and
auditor and succeeded only for dba, the one role that needs no scan. Worse, the
adjacent shape is fatal: joining a masked table under a masked role SEGFAULTS the
backend and restarts the whole Aurora instance. So the persona SELECTs its own
rows, and Python does the matching.

Matching is normalized, not literal. The same statement appears indented as the
lab wrote it, re-rendered with collapsed whitespace, and again inside a jsonb
column where every newline became the two characters backslash-n. A literal
comparison misses two of those three forms, so both sides collapse
``(\\s|\\[a-z])+`` to a single space - the same normalization
``retrieval.refresh_mask_blob()`` builds into the mask itself.

What this gate does NOT claim: that no SQL text is visible anywhere. sql/12
documents two current workshop chunks that legitimately carry the participant's
own DML (the Lock:relation proof and its remediation), and those rows ARE the lab.
The enforced claim is narrower and true: the resolved statement text of a
RESTRICTED observation is unreadable to a persona without clearance in every
column a masking policy covers, and unreachable in the chunk corpus. The
uncleared baseline is measured per literal from the owner's side, so a literal
that legitimately appears in a workshop-visible chunk is held to the count the
DDL implies rather than to zero.

Read-only: SELECT, ``SET LOCAL ROLE``, ROLLBACK. Roles, extension, or capture
absent -> BLOCKED.
"""

from __future__ import annotations

from pathlib import Path
import re
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

GATE_ID = "G-29"
TITLE = "Column masking + Law-2 determinism"

PERSONA_ROLES = ("persona_app_engineer", "persona_dba", "persona_auditor")
CLEARANCE_GROUP = "can_see_restricted"

# WHICH TABLE MUST BE MASKED FOR WHICH PERSONA, pinned here rather than read back
# from the catalog. This is the gate's only independent statement of intent, and
# every one of the three regressions that defeated the catalog-derived version is
# a mutation of exactly this mapping:
#
#   * DROP a policy       -> the table leaves ddm_policies, so the loop that
#                            asserts it stops running. Measured: G-29 stayed green
#                            while 240 rows went raw for both uncleared personas.
#   * WIDEN the role list -> adding persona_dba makes the gate assert "dba should
#                            be masked", which the broken schema satisfies. The
#                            unmasked baseline the lab compares against is now
#                            redacted and "cleared reads raw" proves nothing.
#                            Measured: green, with 80 column scans instead of 70.
#   * NARROW it           -> removing persona_app_engineer makes the gate assert
#                            "app_engineer should read raw", which the broken
#                            schema also satisfies. Measured: green, 60 scans.
#
# A subject that supplies its own expectations cannot fail. The catalog still
# provides the masked COLUMN list and the allow list -- those are shape, and a new
# column being masked is not a regression -- but the role mapping is the security
# claim, so it is written down. Keep in sync with sql/12_masking.sql section 3.
#
# Policy NAMES are deliberately not pinned: a rename that preserves the mapping is
# not a regression, and pinning them would fail on a cosmetic edit.
MASKED_FOR = {
    "casework.pg_stat_activity_samples": ("persona_app_engineer", "persona_auditor"),
    "casework.pg_stat_statements_samples": ("persona_app_engineer", "persona_auditor"),
}

# Tables that must carry NO masking policy, for reasons measured rather than
# assumed. Dropping casework.telemetry_evidence from MASKED_FOR above would
# otherwise weaken this gate silently: an absent table is simply not asserted, so
# re-adding the policy would go unnoticed. This turns the absence into a claim.
#
# Both entries crash or break something and protect nothing, because
# retrieval.chunks.chunk_text is the unmasked indexed copy of the same text
# (see sql/12_masking.sql section 3 for the full measurement):
#
#   * casework.telemetry_evidence -- a mask here made
#     SET LOCAL ROLE persona_auditor; SELECT count(*) FROM
#     casework.v_evidence_documents terminate the backend and restart the whole
#     Aurora instance, because that view joins the masked table. Measured
#     2026-08-03. It also protected nothing: all 5 of 5 restricted statements it
#     redacted appear verbatim in a chunk the auditor reads raw.
#   * retrieval.chunks -- a mask on chunk_text makes every search function fail
#     with "failed to postpone qual containing lateral reference", because all
#     three return a snippet from a LATERAL subquery.
MUST_NOT_BE_MASKED = (
    "casework.telemetry_evidence",
    "retrieval.chunks",
)

# The policy set, read from the extension's own catalog rather than restated here,
# so a policy this file does not know about is asserted too.
#
# The view is pgcolumnmask.ddm_policies. pgcolumnmask.masking_policies does not
# exist; naming it raises UndefinedTable at plan time, which main_guard reports as
# a traceback rather than a verdict.
POLICIES_SQL = """
SELECT p.schemaname || '.' || p.tablename AS qualified,
       p.policyname,
       p.roles,
       p.masked_columns,
       p.predicate_allow_list
  FROM pgcolumnmask.ddm_policies p
 ORDER BY 1, 2
"""

# Every masked table's primary key, from the catalog: the comparison is keyed row
# by row against the owner's stored value, so a table-specific key column cannot
# be hardcoded. Single-column keys only -- all four masked tables have one, and a
# composite key would need a different SELECT shape.
PRIMARY_KEY_SQL = """
SELECT a.attname
  FROM pg_index i
  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
 WHERE i.indrelid = %s::regclass
   AND i.indisprimary
"""

EXTENSION_SQL = "SELECT extversion FROM pg_extension WHERE extname = 'pg_columnmask'"

ROLES_SQL = "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)"

LITERALS_SQL = "SELECT literal FROM retrieval.sensitive_literals() ORDER BY 1"

# The chunk corpus, as the persona reads it: retrieval.chunks ALONE, with no join.
#
# The join is deliberately absent and its absence is load-bearing. An earlier
# version selected the document label alongside the text via
#   JOIN retrieval.documents d ON d.document_version_id = c.document_version_id
# which is a correct many-to-one join (document_version_id is documents' primary
# key) and still destroyed the assertion: retrieval.documents carries its own RLS
# policy, so the join filtered the result before this gate could judge it. Measured
# with retrieval.chunks' policy loosened to USING (true): persona_app_engineer read
# all 110 chunks on a bare SELECT while the joined query still returned 105, and
# the gate reported PASS on a schema that had handed the uncleared persona every
# restricted chunk. A scan for what a persona can read must not read through a
# second protected table -- the other table's protection becomes the answer.
#
# The document label is dropped with it. It only decorated the output, and
# recovering it would require the join that caused the fail-open.
CHUNK_CORPUS_SQL = """
SELECT c.chunk_version_id, c.chunk_ordinal, c.chunk_text
  FROM retrieval.chunks c
 WHERE c.is_current
 ORDER BY c.chunk_version_id
"""

# Chunk text by classification, as the OWNER reads it: the two baselines the corpus
# scan is judged against. A literal reachable only through restricted chunks must be
# unreachable without clearance; one that also appears in a workshop-visible chunk
# is held to that count instead of to zero.
#
# Keyed on retrieval.chunks' own denormalized acl_visibility (sql/01_schema.sql
# carries the scalar on the derived tables), which is the exact column the row policy
# tests. Reaching the classification through casework.evidence_items instead would
# mean a two-table join, and both of those tables are protected -- the same
# fail-open behavior the corpus check above documents, on the oracle side rather than
# the measurement side. Drift between this scalar and the authoritative acl jsonb is
# not this gate's job: G-27 asserts the classification matches the capture.
CHUNKS_BY_VISIBILITY_SQL = """
SELECT c.chunk_text
  FROM retrieval.chunks c
 WHERE c.is_current
   AND coalesce(c.acl_visibility, 'restricted') = %s
"""

# Collapse real whitespace AND the two-character escape sequences a jsonb
# serialization leaves behind, so one literal matches all three renderings of the
# same statement. Mirrors the matcher retrieval.refresh_mask_blob() generates.
_WHITESPACE = re.compile(r"(\s|\\[a-z])+")


def _normalize(value: str | None) -> str:
    """Return ``value`` with every whitespace or escape run collapsed to one space."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", value).strip().lower()


def _as_persona(conn, persona: str, statement: str, params: list) -> list[tuple]:
    """Run one read-only SELECT under ``persona`` and roll the transaction back."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(statement, params)
            return [tuple(row) for row in cur.fetchall()]
        finally:
            cur.execute("ROLLBACK")


def _select_statement(table: str, key: str, columns: list[str]) -> str:
    """Return a keyed all-rows SELECT for one masked table.

    Every masked column is cast to text so a jsonb mask and a text mask compare the
    same way, and the key is cast too so the client-side dict keys are hashable
    regardless of the key's type.
    """
    masked = ", ".join(f"{column}::text" for column in columns)
    return f"SELECT {key}::text, {masked} FROM {table} ORDER BY 1"


def _measure_policies(cur) -> list[dict] | str:
    """Read every masking policy and the owner's stored value for its columns.

    Returns:
        A list of measured policy dicts, or a BLOCKED reason string.
    """
    cur.execute(POLICIES_SQL)
    rows = cur.fetchall()
    if not rows:
        return "no masking policy exists yet; sql/12_masking.sql has not run"
    measured = []
    for qualified, name, roles, columns, allow_list in rows:
        cur.execute(PRIMARY_KEY_SQL, [qualified])
        keys = [row[0] for row in cur.fetchall()]
        if len(keys) != 1:
            return (
                f"{qualified} has a {len(keys)}-column primary key {keys}; this gate "
                f"compares rows by a single key and cannot judge that table"
            )
        statement = _select_statement(qualified, keys[0], list(columns))
        cur.execute(statement)
        stored = {row[0]: row[1:] for row in cur.fetchall()}
        measured.append(
            {
                "table": qualified,
                "policy": name,
                "roles": list(roles),
                "columns": list(columns),
                "allow_list": list(allow_list or []),
                "statement": statement,
                "stored": stored,
            }
        )
    return measured


def _measure_preconditions(cur) -> str | None:
    """Return a BLOCKED reason when the extension or the persona roles are absent."""
    cur.execute(EXTENSION_SQL)
    if cur.fetchone() is None:
        return "pg_columnmask is not installed yet"
    wanted = PERSONA_ROLES + (CLEARANCE_GROUP,)
    cur.execute(ROLES_SQL, [list(wanted)])
    missing = sorted(set(wanted) - {row[0] for row in cur.fetchall()})
    if missing:
        return f"roles not created yet: {', '.join(missing)}"
    return None


def _measure_capture(cur) -> dict | str:
    """Read the A5 literals and the two owner-side corpus baselines."""
    cur.execute(LITERALS_SQL)
    literals = [row[0] for row in cur.fetchall()]
    if not literals:
        return (
            "retrieval.sensitive_literals() is empty; no restricted captured "
            "statement exists yet, so every assertion below would hold vacuously. "
            "Run make live-workshop before this gate"
        )
    cur.execute(CHUNKS_BY_VISIBILITY_SQL, ["restricted"])
    restricted_chunks = [row[0] for row in cur.fetchall()]
    cur.execute(CHUNKS_BY_VISIBILITY_SQL, ["workshop"])
    workshop_chunks = [row[0] for row in cur.fetchall()]
    return {
        "literals": literals,
        "restricted_chunks": restricted_chunks,
        "workshop_chunks": workshop_chunks,
    }


def _measure_as_owner(psycopg, owner_dsn: str) -> dict | str:
    """Measure the policy set, the capture's literals, and the corpus baselines.

    Everything here is read as the schema owner, unfiltered and unmasked, because
    that stored value is the only honest oracle: a persona view judged against
    another persona view cannot distinguish "raw" from "masked differently".
    """
    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            blocked = _measure_preconditions(cur)
            if blocked:
                return blocked

            cur.execute(EXTENSION_SQL)
            extension = cur.fetchone()[0]

            policies = _measure_policies(cur)
            if isinstance(policies, str):
                return policies

            capture = _measure_capture(cur)
            if isinstance(capture, str):
                return capture

    return {"extension": extension, "policies": policies, **capture}


def _count_hits(literal: str, values: list[str | None]) -> int:
    """Return how many of ``values`` contain ``literal`` after normalization."""
    needle = _normalize(literal)
    if not needle:
        return 0
    return sum(1 for value in values if needle in _normalize(value))


def _column_verdict(entry: dict, index: int, rows: list[tuple]) -> tuple[int, int]:
    """Return ``(differs, matches)`` for one masked column against stored truth."""
    stored = entry["stored"]
    differs = matches = 0
    for row in rows:
        key = row[0]
        if key not in stored:
            continue
        if row[index + 1] == stored[key][index]:
            matches += 1
        else:
            differs += 1
    return differs, matches


def _assert_coverage(policies: list[dict]) -> None:
    """Assert the live policy set matches MASKED_FOR - coverage and role mapping.

    This is the only assertion whose expectation does not come from the catalog,
    and that is the entire point: every other check in this gate iterates the live
    policy set, so a dropped policy leaves the loop and a re-scoped role list
    relabels which persona gets which assertion. All three mutations were measured
    green before this check existed.
    """
    covered = {entry["table"]: entry for entry in policies}
    print(
        f"\n  (0) coverage - {len(MASKED_FOR)} tables sql/12 must mask, "
        f"{len(MUST_NOT_BE_MASKED)} it must not:"
    )
    drift = []
    for table, expected in MASKED_FOR.items():
        entry = covered.get(table)
        actual = tuple(sorted(entry["roles"])) if entry else ()
        matches = actual == tuple(sorted(expected))
        print(
            f"    {table}: "
            + (f"masked for {', '.join(actual) or 'no role'}" if entry else "NO POLICY")
            + ("" if matches else f"  <-- expected {', '.join(expected)}")
        )
        if not matches:
            drift.append(f"{table} masks for [{', '.join(actual)}], expected "
                         f"[{', '.join(expected)}]")
    for table in MUST_NOT_BE_MASKED:
        entry = covered.get(table)
        print(
            f"    {table}: "
            + (
                f"MASKED for {', '.join(sorted(entry['roles']))}  <-- must carry "
                "no policy"
                if entry
                else "no policy (required)"
            )
        )
        if entry:
            drift.append(
                f"{table} carries masking policy '{entry['policy']}'; this table "
                f"must not be masked"
            )
    require(
        not drift,
        "the live masking policies do not match the mapping sql/12_masking.sql "
        "section 3 establishes: "
        + "; ".join(drift)
        + ". Widening the list redacts the cleared baseline the lab compares "
        "against; narrowing it hands an uncleared persona the raw column; dropping "
        "the policy does both. All three keep every downstream assertion in this "
        "gate green, because those read the role list from the catalog they judge. "
        "Masking a MUST_NOT_BE_MASKED table crashes the instance or breaks every "
        "search function, and protects nothing either way",
    )


def _assert_masked_role(entry: dict, persona: str, rows: list[tuple]) -> None:
    """Assert every masked column differs from the owner's value for a named role."""
    table = entry["table"]
    for index, column in enumerate(entry["columns"]):
        differs, matches = _column_verdict(entry, index, rows)
        print(f"      {column}: masked={differs} raw={matches}")
        require(
            differs > 0,
            f"{persona} is named by masking policy {entry['policy']} on {table}, but "
            f"not one of its {differs + matches} readable rows returns a {column} "
            f"that differs from the owner's stored value -- the column is not masked "
            f"for it at all. Check that the policy's masking expression names "
            f"{column} and that the persona holds EXECUTE on the mask function "
            f"(sql/12_masking.sql sections 3 and 4)",
        )


def _assert_unmasked_role(entry: dict, persona: str, rows: list[tuple]) -> None:
    """Assert every masked column is raw for a role the policy does not name."""
    table = entry["table"]
    for index, column in enumerate(entry["columns"]):
        differs, matches = _column_verdict(entry, index, rows)
        print(f"      {column}: masked={differs} raw={matches}")
        require(
            differs == 0,
            f"{persona} is NOT named by masking policy {entry['policy']} on {table}, "
            f"yet {differs} of its {differs + matches} readable rows return a "
            f"{column} that differs from the owner's stored value. The mask is not "
            f"role-scoped, so the unmasked baseline the lab compares against is "
            f"itself redacted and 'cleared reads raw, uncleared reads redacted' "
            f"proves nothing (sql/12_masking.sql section 3)",
        )


def _assert_masking_is_real(app_conn, policies: list[dict]) -> dict:
    """Group (1): every policy, every masked column, both directions.

    Returns:
        ``table -> persona -> rows`` for the reads taken here, so the determinism
        group can replay them without re-deciding what to read.
    """
    print("\n  (1) masking is real - per policy, per column, against stored truth:")
    reads: dict[str, dict[str, list[tuple]]] = {}
    for entry in policies:
        table = entry["table"]
        print(
            f"\n    {table} [{entry['policy']}] masks {', '.join(entry['columns'])} "
            f"for {', '.join(entry['roles']) or 'no role'}"
            + (f" (predicate allow list: {', '.join(entry['allow_list'])})"
               if entry["allow_list"] else "")
        )
        reads[table] = {}
        for persona in PERSONA_ROLES:
            rows = _as_persona(app_conn, persona, entry["statement"], [])
            reads[table][persona] = rows
            named = persona in entry["roles"]
            print(
                f"    {persona}: {len(rows)} readable rows, "
                f"policy {'names' if named else 'does not name'} it"
            )
            require(
                rows,
                f"{persona} reads no rows at all from {table}, so masking cannot be "
                f"judged there. Masking needs the row PRESENT: if RLS is hiding "
                f"every row the two mechanisms have been confused "
                f"(sql/11_roles_rls.sql owns rows, sql/12_masking.sql owns columns)",
            )
            if named:
                _assert_masked_role(entry, persona, rows)
            else:
                _assert_unmasked_role(entry, persona, rows)
    return reads


def _assert_determinism(app_conn, policies: list[dict], reads: dict) -> None:
    """Group (2): Law 2 - the same persona replays byte-identically."""
    print("\n  (2) Law 2 determinism - same persona, two transactions:")
    for entry in policies:
        table = entry["table"]
        for persona in entry["roles"]:
            if persona not in PERSONA_ROLES:
                continue
            replay = _as_persona(app_conn, persona, entry["statement"], [])
            first = reads[table][persona]
            print(f"    {table} as {persona}: identical={replay == first}")
            require(
                replay == first,
                f"{persona} read {table} twice and the masked values differ between "
                f"transactions. The panel and its pasted _verify_sql run the same "
                f"masked expression, so a non-deterministic mask makes the receipt "
                f"unreproducible (Law 2). Every mask function must be IMMUTABLE "
                f"(sql/12_masking.sql section 1)",
            )


def _assert_column_carries_no_literal(
    literals: list[str], entry: dict, persona: str, index: int, values: list
) -> None:
    """Assert one masked column, as one named role, returns no captured literal."""
    table, column = entry["table"], entry["columns"][index]
    hits = [
        (i, n)
        for i, n in ((i, _count_hits(lit, values)) for i, lit in enumerate(literals))
        if n
    ]
    print(
        f"    {table}.{column} as {persona}: "
        + (f"LEAK {hits}" if hits else f"0 hits over {len(literals)} literals")
    )
    require(
        not hits,
        f"{persona} read a captured restricted statement out of {table}.{column}, "
        f"which masking policy {entry['policy']} names: "
        + "; ".join(f"literal {i} x{n}" for i, n in hits)
        + ". A substring mask cannot match text the source system rewrote before "
        "storing it, and a whole-value mask on the wrong column leaves the copy "
        "one column over intact -- both were measured. Check the masking "
        "expression covers this column's rendering (sql/12_masking.sql section 3)",
    )


def _assert_masked_columns_carry_no_literal(
    literals: list[str], policies: list[dict], reads: dict
) -> int:
    """Group (4a): no masked column returns a captured statement to a named role."""
    print("\n  (4a) A5 leak scan - masked columns, in the persona's own result set:")
    scanned = 0
    for entry in policies:
        for persona in [r for r in entry["roles"] if r in PERSONA_ROLES]:
            for index in range(len(entry["columns"])):
                values = [row[index + 1] for row in reads[entry["table"]][persona]]
                _assert_column_carries_no_literal(
                    literals, entry, persona, index, values
                )
                scanned += len(literals)
    return scanned


def _corpus_baseline(measured: dict) -> dict[str, tuple[int, int]]:
    """Return ``literal -> (workshop_hits, restricted_hits)`` measured as the owner."""
    return {
        literal: (
            _count_hits(literal, measured["workshop_chunks"]),
            _count_hits(literal, measured["restricted_chunks"]),
        )
        for literal in measured["literals"]
    }


def _assert_persona_corpus(persona: str, rows: list[tuple], baseline: dict) -> int:
    """Assert one persona's chunk reads match the visibility baseline, per literal."""
    texts = [row[2] for row in rows]
    cleared = persona != "persona_app_engineer"
    total = 0
    for index, (literal, (workshop, restricted)) in enumerate(baseline.items()):
        hits = _count_hits(literal, texts)
        total += hits
        expected = workshop + (restricted if cleared else 0)
        require(
            hits == expected,
            f"{persona} matched literal {index} in {hits} of its {len(rows)} current "
            f"chunks; the owner measured {workshop} workshop-visible and {restricted} "
            f"restricted, so it should match {expected}. "
            + (
                "Reading more means a restricted chunk is reachable without "
                "clearance: chunk_text is protected by RLS, not by masking "
                "(sql/11_roles_rls.sql sections 4-5)"
                if hits > expected
                else "Reading fewer means a workshop-visible chunk this persona must "
                "reach is being filtered, which removes evidence the lab depends on"
            ),
        )
    return total


def _assert_corpus_scan(app_conn, measured: dict) -> None:
    """Group (4b): the chunk corpus, held to the baseline the DDL implies.

    retrieval.chunks.chunk_text is deliberately NOT masked (sql/12 section 3: a
    mask there breaks the LATERAL snippet SELECT in every search function), so
    RLS is what protects it. The assertion is therefore not "zero hits" -- two
    current workshop chunks legitimately carry the participant's own DML, and
    demanding zero would demand hiding the lab from the persona investigating it.
    The baseline is measured from the owner's side per literal: a literal reachable
    only through restricted chunks must be unreachable without clearance.
    """
    print("\n  (4b) A5 leak scan - current chunk corpus:")
    baseline = _corpus_baseline(measured)
    workshop_total = sum(workshop for workshop, _ in baseline.values())
    restricted_total = sum(restricted for _, restricted in baseline.values())
    for persona in PERSONA_ROLES:
        rows = _as_persona(app_conn, persona, CHUNK_CORPUS_SQL, [])
        total = _assert_persona_corpus(persona, rows, baseline)
        expected = workshop_total + (
            restricted_total if persona != "persona_app_engineer" else 0
        )
        print(
            f"    {persona}: {total} literal hit(s) across {len(rows)} current "
            f"chunks (expected {expected})"
        )


def _report_literals(measured: dict) -> None:
    """Group (3): show the capture-derived pattern set and where it came from."""
    literals = measured["literals"]
    print(
        f"\n  (3) A5 pattern provenance - retrieval.sensitive_literals(), "
        f"{len(literals)} literal(s) from this capture:"
    )
    for index, literal in enumerate(literals):
        collapsed = _WHITESPACE.sub(" ", literal).strip()
        print(f"    [{index}] {collapsed[:96]!r}")
    print(
        f"    owner reach: {len(measured['restricted_chunks'])} restricted and "
        f"{len(measured['workshop_chunks'])} workshop-visible current chunks"
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

    print(f"  pg_columnmask: {measured['extension']}")
    policies = measured["policies"]
    _assert_coverage(policies)
    _report_literals(measured)

    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app_conn:
        # A missing SELECT grant is an unbuilt sql/11 dependency, not a masking
        # defect. main_guard translates only AssertionError, so an escaping
        # InsufficientPrivilege would be a traceback where the contract wants an
        # honest BLOCKED.
        try:
            reads = _assert_masking_is_real(app_conn, policies)
            _assert_determinism(app_conn, policies, reads)
            scanned = _assert_masked_columns_carry_no_literal(
                measured["literals"], policies, reads
            )
            _assert_corpus_scan(app_conn, measured)
        except psycopg.errors.InsufficientPrivilege as exc:
            return finish(
                GATE_ID, BLOCKED, f"a persona lacks SELECT on the read path: {exc}"
            )

    masked_columns = sum(len(entry["columns"]) for entry in policies)
    return finish(
        GATE_ID,
        PASS,
        f"{len(policies)} masking policies over {masked_columns} columns: every named "
        f"role reads redacted and every unnamed role reads the owner's stored value, "
        f"byte-stable across transactions; {len(measured['literals'])} capture-derived "
        f"literals absent from all masked columns ({scanned} column scans) and the "
        f"chunk corpus matches the visibility baseline",
    )


if __name__ == "__main__":
    main_guard(run)
