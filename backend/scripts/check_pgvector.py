from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import close_pool, get_owner_conn


def version_tuple(value: str | bytes | None) -> tuple[int, ...]:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    match = re.search(r"(\d+(?:\.\d+)*)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pgvector availability and installed version.")
    parser.add_argument("--min-version", default="0.8.1")
    parser.add_argument("--available", action="store_true", help="Check pg_available_extensions before CREATE EXTENSION runs")
    args = parser.parse_args()

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            if args.available:
                cur.execute("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
                row = cur.fetchone()
                if not row:
                    print("pgvector is not available to this Postgres server.", file=sys.stderr)
                    return 1
                actual = row[0]
                source = "available"
            else:
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                row = cur.fetchone()
                if not row:
                    print("pgvector is not installed in this database.", file=sys.stderr)
                    return 1
                actual = row[0]
                source = "installed"

    if version_tuple(actual) < version_tuple(args.min_version):
        print(f"pgvector {source} version is {actual}; expected >= {args.min_version}.", file=sys.stderr)
        return 1

    print(f"pgvector {source} version OK: {actual}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        close_pool()
