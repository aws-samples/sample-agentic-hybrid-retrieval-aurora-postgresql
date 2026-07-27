from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import close_pool, get_conn


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PostgreSQL server version.")
    parser.add_argument("--min-version", default="18.3")
    args = parser.parse_args()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            actual = cur.fetchone()[0]

    if version_tuple(actual) < version_tuple(args.min_version):
        print(f"PostgreSQL server version is {actual}; expected >= {args.min_version}.", file=sys.stderr)
        return 1

    print(f"PostgreSQL server version OK: {actual}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        close_pool()
