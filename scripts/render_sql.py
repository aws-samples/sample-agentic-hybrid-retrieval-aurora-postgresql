#!/usr/bin/env python3
"""Render SQL files for a chosen vector dimension."""
from __future__ import annotations
import argparse, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vector-dim", type=int, default=1024)
    ap.add_argument("--output", type=Path, default=ROOT / "build" / "sql")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for src in sorted((ROOT / "sql").glob("*.sql")):
        text = src.read_text(encoding="utf-8")
        text = re.sub(r"vector\(\d+\)", f"vector({args.vector_dim})", text)
        (args.output / src.name).write_text(text, encoding="utf-8")
    print(f"Rendered SQL for vector({args.vector_dim}) in {args.output}")

if __name__ == "__main__":
    main()
