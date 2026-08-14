#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "SHA256SUMS"

lines = []
for path in sorted(ROOT.rglob("*")):
    if (
        not path.is_file()
        or path == OUTPUT
        or path.name.endswith(".pyc")
        or "__pycache__" in path.parts
    ):
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.relative_to(ROOT)}")
OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {len(lines)} checksums")
