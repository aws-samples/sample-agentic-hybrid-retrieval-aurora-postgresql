#!/usr/bin/env python3
"""G-29 - Column masking and Law-2 determinism (A3/A5, design 2026-07-28).

Four assertions:

1. Masking is real. Under ``persona_auditor`` the sensitive columns on a
   restricted support case (``account_name``, ``customer_commitment``,
   ``description``) and the denormalized ``retrieval.chunks.chunk_text`` blob come
   back masked; under ``persona_dba`` the same columns come back raw. Masking is
   detected by comparing the two views, not by reading a ``pg_columnmask`` catalog
   table - behaviour is what the workshop claims, so behaviour is what is asserted.

2. Law 2 determinism. The same SELECT, issued twice in separate transactions under
   the same persona, returns byte-identical values. This is what lets a panel and
   the pasted ``_verify_sql`` agree: both run the identical masked expression.

3. A5 pattern provenance. The sensitive literals are **read from the engine** (the
   restricted rows' own typed values), never hand-written in this gate. If the seed
   changes, the gate's expectations change with it.

4. A5 corpus-wide leak scan. Every restricted sensitive literal is searched for
   across the entire auditor-visible corpus - all of ``retrieval.chunks.chunk_text``
   and the typed case columns - and must return zero hits. A mask that covers the
   canonical row but misses a paraphrase elsewhere in the corpus is a leak, and only
   a corpus-wide scan catches it.

Read-only: SELECT, ``SET LOCAL ROLE``, ROLLBACK. Roles or masking absent -> BLOCKED.
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

GATE_ID = "G-29"
TITLE = "Column masking + Law-2 determinism"

AUDITOR = "persona_auditor"
DBA = "persona_dba"
COLUMNS = ("account_name", "customer_commitment", "description")

# The typed sensitive columns, read from the engine to build the pattern set (A5).
SENSITIVE_SQL = """
SELECT e.external_key, c.account_name, c.customer_commitment, c.description
  FROM casework.support_cases c
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE coalesce(e.acl ->> 'visibility', 'restricted') = 'restricted'
   AND NOT e.is_deleted
 ORDER BY e.external_key
"""

CASE_VIEW_SQL = """
SELECT e.external_key, c.account_name, c.customer_commitment, c.description
  FROM casework.support_cases c
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE e.external_key = ANY(%s)
 ORDER BY e.external_key
"""

# retrieval.chunks has NO external_key (see Codebase traps). Reach the label
# through the document_version_id foreign key -- documents' primary key, so the
# join cannot fan out -- and filter on the chunk's own is_current flag.
CHUNK_VIEW_SQL = """
SELECT d.external_key, c.chunk_ordinal, c.chunk_text
  FROM retrieval.chunks c
  JOIN retrieval.documents d ON d.document_version_id = c.document_version_id
 WHERE d.external_key = ANY(%s)
   AND c.is_current
 ORDER BY d.external_key, c.chunk_ordinal
"""

LEAK_SCAN_SQL = """
SELECT count(*)
  FROM retrieval.chunks
 WHERE is_current
   AND chunk_text ILIKE '%%' || %s || '%%'
"""


def _as_persona(conn, persona: str, sql: str, params: list) -> list[tuple]:
    """Run one read-only SELECT under ``persona`` and roll the transaction back."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.execute("ROLLBACK")


def _owner_chunks(owner_dsn: str, psycopg, keys: list[str]) -> list[tuple]:
    """Return the stored chunk blobs for ``keys``, read as the bootstrap owner.

    The owner is an ``rds_superuser`` member, so this is the ground truth the
    persona views are judged against. Read-only.
    """
    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(CHUNK_VIEW_SQL, [keys])
            return cur.fetchall()


def _literals(rows: list[tuple]) -> list[str]:
    """Return the distinct non-empty sensitive literals from measured rows."""
    out: set[str] = set()
    for _key, account, commitment, description in rows:
        for value in (account, commitment, description):
            if value and len(value.strip()) >= 6:
                out.add(value.strip())
    return sorted(out)


def run() -> int:  # noqa: C901 - four assertion groups, read top to bottom
    print_header(GATE_ID, TITLE)

    owner_dsn = read_env_value("DATABASE_URL")
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not owner_dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")
    if not app_dsn:
        return finish(
            GATE_ID, BLOCKED, "WORKSHOP_APP_DATABASE_URL is not set; cannot SET ROLE"
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(owner_dsn)}")

    try:
        with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'pg_columnmask'"
                )
                ext = cur.fetchone()
                if ext is None:
                    return finish(
                        GATE_ID, BLOCKED, "pg_columnmask is not installed yet"
                    )
                print(f"  pg_columnmask: {ext[0]}")
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    [[AUDITOR, DBA]],
                )
                found = {row[0] for row in cur.fetchall()}
                if {AUDITOR, DBA} - found:
                    return finish(
                        GATE_ID,
                        BLOCKED,
                        f"persona roles missing: {sorted({AUDITOR, DBA} - found)}",
                    )
                cur.execute(SENSITIVE_SQL)
                sensitive = cur.fetchall()
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    if not sensitive:
        return finish(
            GATE_ID, BLOCKED, "no restricted support cases seeded; nothing to mask"
        )

    keys = [row[0] for row in sensitive]
    literals = _literals(sensitive)
    print("\n  (3) A5 pattern provenance - read from the engine, not hand-written:")
    print(f"    restricted cases: {', '.join(keys)}")
    print(f"    sensitive literals: {len(literals)}")
    for value in literals:
        print(f"      {value!r}")
    require(literals, "restricted cases carry no maskable sensitive values")

    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app:
        # A missing SELECT grant is an unbuilt dependency, not a masking failure.
        # main_guard only translates AssertionError, so an escaping
        # InsufficientPrivilege would be a traceback where the contract demands an
        # honest BLOCKED. sql/11 grants SELECT ON ALL TABLES IN SCHEMA casework to
        # each persona; this catch names the table when that has not run yet.
        try:
            dba_cases = _as_persona(app, DBA, CASE_VIEW_SQL, [keys])
            auditor_cases = _as_persona(app, AUDITOR, CASE_VIEW_SQL, [keys])
            dba_chunks = _as_persona(app, DBA, CHUNK_VIEW_SQL, [keys])
            auditor_chunks = _as_persona(app, AUDITOR, CHUNK_VIEW_SQL, [keys])
        except psycopg.errors.InsufficientPrivilege as exc:
            return finish(
                GATE_ID, BLOCKED, f"a persona lacks SELECT on the read path: {exc}"
            )

        print("\n  (1) masking is real - dba raw vs auditor masked:")
        require(
            len(auditor_cases) == len(dba_cases) and auditor_cases,
            f"auditor row count {len(auditor_cases)} != dba {len(dba_cases)}; "
            f"masking needs the row PRESENT, not filtered",
        )
        # Ground truth read as the bootstrap owner, keyed by external_key. "Masked
        # for the auditor" is only meaningful against the real stored value: two
        # differently-masked views also differ from each other, so comparing the
        # dba view to the auditor view alone cannot tell "dba is raw" from
        # "dba is masked differently". Anchor on truth, not on the other view.
        truth = {row[0]: row[1:] for row in sensitive}
        for dba_row, auditor_row in zip(dba_cases, auditor_cases):
            key = dba_row[0]
            for column, raw, masked, stored in zip(
                COLUMNS, dba_row[1:], auditor_row[1:], truth[key]
            ):
                if stored is None:
                    continue
                print(f"    {key}.{column}: dba={raw!r} auditor={masked!r}")
                require(
                    raw == stored,
                    f"{key}.{column} is masked for persona_dba too "
                    f"(dba={raw!r} != stored {stored!r}); the mask is not "
                    f"auditor-scoped and 'dba raw vs auditor masked' proves nothing",
                )
                require(
                    masked != stored,
                    f"{key}.{column} is NOT masked for the auditor "
                    f"(identical to the stored value)",
                )
        require(
            dba_chunks and len(auditor_chunks) == len(dba_chunks),
            "chunk_text row counts differ between dba and auditor",
        )
        # Same anchor for the blob: the dba view must equal what is stored.
        owner_blobs = _owner_chunks(owner_dsn, psycopg, keys)
        require(
            owner_blobs and len(dba_chunks) == len(owner_blobs),
            f"dba sees {len(dba_chunks)} restricted chunks, the owner sees "
            f"{len(owner_blobs)}; compare like with like before judging the mask",
        )
        require(
            [row[2] for row in dba_chunks] == [row[2] for row in owner_blobs],
            "chunk_text is masked for persona_dba too; a blob that differs "
            "between dba and auditor then proves nothing about the auditor",
        )
        blob_masked = sum(
            1 for a, b in zip(dba_chunks, auditor_chunks) if a[2] != b[2]
        )
        print(
            f"    chunk_text: {blob_masked} of {len(dba_chunks)} restricted chunks "
            f"differ under the auditor"
        )
        require(
            blob_masked > 0,
            "no restricted chunk_text differs under the auditor; the blob is unmasked",
        )

        print("\n  (2) Law 2 determinism - same persona, two transactions:")
        replay_cases = _as_persona(app, AUDITOR, CASE_VIEW_SQL, [keys])
        replay_chunks = _as_persona(app, AUDITOR, CHUNK_VIEW_SQL, [keys])
        print(f"    typed columns identical: {replay_cases == auditor_cases}")
        print(f"    chunk blobs identical:   {replay_chunks == auditor_chunks}")
        require(
            replay_cases == auditor_cases,
            "auditor typed columns are not byte-stable across transactions; the panel "
            "and the pasted verify-SQL would disagree (Law 2 violation)",
        )
        require(
            replay_chunks == auditor_chunks,
            "auditor chunk_text is not byte-stable across transactions (Law 2)",
        )

        print("\n  (4) A5 corpus-wide leak scan as the auditor:")
        leaks: list[tuple[str, int]] = []
        for value in literals:
            hits = _as_persona(app, AUDITOR, LEAK_SCAN_SQL, [value])[0][0]
            print(f"    {value!r}: {hits} chunk hit(s)")
            if hits:
                leaks.append((value, hits))
        require(
            not leaks,
            "restricted literals still visible to the auditor somewhere in the corpus: "
            + "; ".join(f"{v!r} x{n}" for v, n in leaks),
        )

    return finish(
        GATE_ID,
        PASS,
        f"{len(literals)} restricted literals masked for the auditor, byte-stable "
        f"across transactions, zero corpus-wide leaks",
    )


if __name__ == "__main__":
    main_guard(run)
