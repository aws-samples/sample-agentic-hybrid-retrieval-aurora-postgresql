"""Keep db/SHA256SUMS aligned with the files it claims to describe.

The manifest is produced by db/scripts/build_checksums.py and consumed by
release reviewers; without this gate nothing verifies it, so an edit to any
db/ file without a regeneration would ship a manifest that lies.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db"
MANIFEST = DB / "SHA256SUMS"


def computed_checksums() -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in sorted(DB.rglob("*")):
        if (
            not path.is_file()
            or path == MANIFEST
            or path.name.endswith(".pyc")
            or "__pycache__" in path.parts
        ):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums[str(path.relative_to(DB))] = digest
    return checksums


def recorded_checksums() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def test_sha256sums_matches_the_db_tree():
    assert recorded_checksums() == computed_checksums(), (
        "db/SHA256SUMS drifted from the db/ tree; regenerate it with "
        "python db/scripts/build_checksums.py"
    )
