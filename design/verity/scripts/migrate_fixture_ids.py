#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_MAP = Path(__file__).resolve().parents[1] / "fixtures" / "id-migration.json"

def migrate_text(text: str, mapping: dict[str, str]) -> str:
    # Longest keys first prevents composite IDs from being partially replaced.
    for old in sorted(mapping, key=len, reverse=True):
        text = text.replace(old, mapping[old])
    return text

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="Files to migrate in place")
    parser.add_argument("--map", default=str(DEFAULT_MAP))
    parser.add_argument("--check", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    changed = 0

    for raw in args.paths:
        path = Path(raw)
        before = path.read_text(encoding="utf-8")
        after = migrate_text(before, mapping)
        if before == after:
            continue
        changed += 1
        print(f"{'WOULD CHANGE' if args.check else 'CHANGED'} {path}")
        if not args.check:
            path.write_text(after, encoding="utf-8")

    print(f"{changed} file(s) changed")

if __name__ == "__main__":
    main()
