#!/usr/bin/env python3
"""Assert exactly one live signature per retrieval function on the cluster.

`CREATE OR REPLACE FUNCTION` cannot change a signature. Adding, removing, or
retyping a parameter creates an **overload** and leaves the previous body live and
callable. A caller passing the old positional argument count then silently binds
the old implementation, which is forked truth at the function level: two
definitions of "the search function" answering different callers, with no error
anywhere.

Measured: Unit D added `trigram_threshold` to `mosaic_search.search_hybrid_rrf`
and left two nine- and ten-argument versions live on Aurora. The SQL file was
correct; the cluster was not.

The SQL file now carries an explicit `DROP FUNCTION IF EXISTS` for the superseded
signature, and this check proves the cluster agrees. Requires a DSN. Set
`FUNCTION_CENSUS_REQUIRE_DB=1` in CI so a missing DSN is a loud failure rather
than a silent skip.

Usage
-----
    uv run python scripts/function_census.py

Exit codes
----------
    0  every retrieval function has exactly one live signature
    1  a duplicate exists, or the census could not run in CI-with-DSN mode
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain

# Schemas whose functions are part of the retrieval contract. A duplicate here is
# a correctness problem; elsewhere it may be a deliberate overload.
SCHEMAS = ("mosaic_search",)

CENSUS_SQL = """
SELECT n.nspname AS schema,
       p.proname AS name,
       count(*) AS signatures,
       array_agg(pg_get_function_identity_arguments(p.oid)
                 ORDER BY p.pronargs) AS argument_lists
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = ANY(%s)
GROUP BY n.nspname, p.proname
ORDER BY n.nspname, p.proname
"""


def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    require_db = os.getenv("FUNCTION_CENSUS_REQUIRE_DB") == "1"
    if not dsn:
        message = (
            "CANNOT VERIFY: DATABASE_URL is not set, so the function census did "
            "not run. A superseded function signature could be live and callable."
        )
        print(f"WARNING: {message}", file=sys.stderr)
        return 1 if require_db else 0

    import psycopg

    with psycopg.connect(dsn, connect_timeout=20) as connection:
        connection.read_only = True
        rows = connection.execute(CENSUS_SQL, (list(SCHEMAS),)).fetchall()

    failures = []
    for schema, name, signatures, argument_lists in rows:
        if signatures > 1:
            failures.append(
                explain(
                    f"{schema}.{name} has {signatures} live signatures "
                    f"{list(argument_lists)}",
                    "DROP the superseded one — CREATE OR REPLACE cannot change a "
                    "signature, so the old body is still callable by any caller "
                    "passing the old argument count",
                )
            )

    print(f"function census: {len(rows)} function name(s) in {', '.join(SCHEMAS)}")
    if failures:
        print(f"\n{len(failures)} duplicate signature(s):", file=sys.stderr)
        for failure in failures:
            print(f"  FAIL {failure}", file=sys.stderr)
        return 1
    print("every retrieval function has exactly one live signature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
