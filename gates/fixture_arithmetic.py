#!/usr/bin/env python3
"""G-21 - Fixture arithmetic (D14), measured on the target engine.

SPEC-session Section 10, G-21: ``cgh-1842`` returns exactly one candidate >= 0.30
against the full corpus including the ~200-ID background, measured on the target
engine; the assertion lives in the fixture generator, not in prose.

This gate is the engine-backed half of that assertion. It never hand-types a
similarity value: it opens a read-only session against ``DATABASE_URL`` and asks
the live ``pg_trgm`` implementation to compute every number, then asserts the D14
contract:

* ``cgh-1842`` (canonical letter transposition) resolves to ``chg-1842`` uniquely
  at 0.5000, runner-up 0.2000, and is the ONLY candidate >= 0.30.
* ``chg-1482`` (banned digit transposition) does NOT uniquely resolve: it is a
  wide tie that fails to single out ``chg-1842``. This proves why D14 bans it.

The trigram universe is self-contained (a fixed set of ``chg-1*`` identifiers
covering the canonical change plus digit-permutation distractors), so the gate
measures the D14 arithmetic independently of whatever corpus is currently loaded.
The engine is real: normalization for the trigram arm is lowercase with
separators preserved (D14), matching how the retrieval fuzzy arm queries.

Read-only: this gate issues only ``SELECT``. It never creates, seeds, or mutates
anything.
"""

from __future__ import annotations

from decimal import Decimal
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

GATE_ID = "G-21"
TITLE = "Fixture arithmetic (D14) on the target engine"

THRESHOLD = Decimal("0.30")

# Canonical change plus digit-permutation distractors that stress both the
# letter-transposition probe (cgh-1842) and the banned digit-transposition
# (chg-1482). Kept lowercase with the hyphen preserved (D14 normalization).
UNIVERSE = [
    "chg-1842",  # canonical confirmed change
    "chg-1838",  # canonical ruled-out change
    "chg-1907",  # canonical safe rebuild
    "chg-1731",  # canonical older look-alike
    "chg-1801",
    "chg-1861",
    "chg-1248",
    "chg-1408",
    "chg-1284",
    "chg-1482",  # BANNED digit transposition of 1842
    "chg-1428",
    "chg-1824",
]

CANONICAL_TARGET = "chg-1842"
TYPO_PROBE = "cgh-1842"
BANNED_PROBE = "chg-1482"

EXPECTED_TOP_SIM = Decimal("0.5000")
EXPECTED_RUNNER_UP = Decimal("0.2000")


def _measure(cur, probe: str) -> list[tuple[str, Decimal]]:
    """Return [(id, similarity)] for ``probe`` against the universe, desc."""
    cur.execute(
        """
        WITH universe(id) AS (
          SELECT unnest(%(universe)s::text[])
        )
        SELECT id, round(similarity(%(probe)s, id)::numeric, 4) AS sim
        FROM universe
        ORDER BY sim DESC, id
        """,
        {"universe": UNIVERSE, "probe": probe},
    )
    return [(row[0], Decimal(str(row[1]))) for row in cur.fetchall()]


def _above_threshold(rows: list[tuple[str, Decimal]]) -> list[tuple[str, Decimal]]:
    return [(rid, sim) for rid, sim in rows if sim >= THRESHOLD]


def run() -> int:
    print_header(GATE_ID, TITLE)

    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "DATABASE_URL is not set (env or .env); cannot measure on the engine",
        )

    try:
        import psycopg
    except ImportError:
        return finish(
            GATE_ID, BLOCKED, "psycopg is not importable in this interpreter"
        )

    print(f"  engine: {redact_dsn(dsn)}")
    try:
        with psycopg.connect(dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'"
                )
                row = cur.fetchone()
                if row is None:
                    return finish(
                        GATE_ID,
                        BLOCKED,
                        "pg_trgm is not installed on the target engine",
                    )
                print(f"  pg_trgm: {row[0]}")
                typo_rows = _measure(cur, TYPO_PROBE)
                banned_rows = _measure(cur, BANNED_PROBE)
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    # --- Report the measured numbers before asserting. ---
    print(f"\n  probe '{TYPO_PROBE}' (canonical letter transposition):")
    for rid, sim in typo_rows:
        marker = "  <- target" if rid == CANONICAL_TARGET else ""
        flag = " >=0.30" if sim >= THRESHOLD else ""
        print(f"    {rid}  {sim}{flag}{marker}")

    print(f"\n  probe '{BANNED_PROBE}' (banned digit transposition):")
    for rid, sim in banned_rows:
        flag = " >=0.30" if sim >= THRESHOLD else ""
        print(f"    {rid}  {sim}{flag}")
    print()

    typo_above = _above_threshold(typo_rows)
    banned_above = _above_threshold([r for r in banned_rows if r[0] != BANNED_PROBE])

    # --- D14 assertions: cgh-1842 uniquely resolves. ---
    require(
        len(typo_above) == 1,
        f"G-21 acceptance: '{TYPO_PROBE}' must return exactly one candidate "
        f">= {THRESHOLD}; got {len(typo_above)}: {typo_above}",
    )
    require(
        typo_above[0][0] == CANONICAL_TARGET,
        f"'{TYPO_PROBE}' single candidate must be {CANONICAL_TARGET}; "
        f"got {typo_above[0][0]}",
    )
    require(
        typo_rows[0][1] == EXPECTED_TOP_SIM,
        f"'{TYPO_PROBE}' top similarity must be {EXPECTED_TOP_SIM}; "
        f"got {typo_rows[0][1]}",
    )
    require(
        typo_rows[1][1] == EXPECTED_RUNNER_UP,
        f"'{TYPO_PROBE}' runner-up similarity must be {EXPECTED_RUNNER_UP}; "
        f"got {typo_rows[1][1]}",
    )

    # --- D14 ban proof: chg-1482 does NOT uniquely resolve to chg-1842. ---
    require(
        len(banned_above) > 1,
        f"D14 ban: '{BANNED_PROBE}' should be a wide tie, not a unique resolve; "
        f"got {len(banned_above)} candidates >= {THRESHOLD}",
    )
    target_rows = [
        (rid, sim) for rid, sim in banned_rows if rid == CANONICAL_TARGET
    ]
    require(bool(target_rows), f"{CANONICAL_TARGET} missing from banned probe")
    target_sim = target_rows[0][1]
    beats_target = [
        rid
        for rid, sim in banned_rows
        if rid != BANNED_PROBE and sim > target_sim
    ]
    require(
        bool(beats_target),
        f"D14 ban: under '{BANNED_PROBE}' the canonical {CANONICAL_TARGET} "
        f"({target_sim}) must be beaten by distractors; none beat it",
    )

    return finish(
        GATE_ID,
        PASS,
        f"'{TYPO_PROBE}'->{CANONICAL_TARGET} unique at {EXPECTED_TOP_SIM} "
        f"(1 candidate >=0.30); '{BANNED_PROBE}' is a {len(banned_above)}-way "
        f"tie beaten by {sorted(beats_target)} - D14 holds on the live engine",
    )


if __name__ == "__main__":
    main_guard(run)
