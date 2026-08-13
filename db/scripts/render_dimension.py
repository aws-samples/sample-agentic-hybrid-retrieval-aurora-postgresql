#!/usr/bin/env python3
"""Render the SQL package for a different vector dimension.

The checked-in SQL uses vector(1024). This utility rewrites every SQL file to a
separate output directory, leaving the source package untouched. It changes the
schema contract only; callers must supply vectors generated in the same target
space.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.dimension <= 16000:
        raise SystemExit("dimension must be between 1 and 16000")

    args.output.mkdir(parents=True, exist_ok=True)
    for source in sorted((ROOT / "sql").glob("*.sql")):
        text = source.read_text(encoding="utf-8")
        rendered = text.replace("vector(1024)", f"vector({args.dimension})")
        (args.output / source.name).write_text(rendered, encoding="utf-8")
    print(f"Rendered SQL to {args.output} with vector dimension {args.dimension}")


if __name__ == "__main__":
    main()
