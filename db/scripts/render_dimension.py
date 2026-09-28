#!/usr/bin/env python3
"""Render the SQL install tree for a different vector dimension.

The checked-in SQL uses vector(1024). This utility rewrites every SQL file
`sql/install.sql` can include, `db/sql/` and the lab files under `labs/`, into
an output directory with the same relative layout, so the install script's
`\\ir ../../labs/...` includes still resolve there. It changes the schema
contract only; callers must supply vectors generated in the same target space.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def sql_sources() -> list[Path]:
    """Every SQL file in the install tree, as paths under the repository."""
    return sorted((ROOT / "sql").glob("*.sql")) + sorted((REPO / "labs").rglob("*.sql"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory that receives db/sql/ and labs/; the repository root renders in place",
    )
    args = parser.parse_args()
    if not 1 <= args.dimension <= 16000:
        raise SystemExit("dimension must be between 1 and 16000")
    for source in sql_sources():
        target = args.output / source.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        rendered = text.replace("vector(1024)", f"vector({args.dimension})")
        target.write_text(rendered, encoding="utf-8")
    print(f"Rendered SQL to {args.output} with vector dimension {args.dimension}")


if __name__ == "__main__":
    main()
