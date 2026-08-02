#!/usr/bin/env python3
"""G-14 - reject canned values in the built participant frontend."""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    repo_root,
)

GATE_ID = "G-14"
TITLE = "Built frontend contains no canned participant evidence"

BUNDLE_DIR = Path("frontend/dist")
SCAN_SUFFIXES = {".js", ".css", ".html", ".json", ".map"}

NUMERAL_DENYLIST = [
    "0.0650",
    "0.06505",
    "0.0491",
    "94.8",
    "12,011",
    "48,226",
    "1,356",
    "1,240",
    "0.5000",
    "0.3846",
]

RECEIPT_DENYLIST = [
    "rr_9b41d7",
    "rr_9b41d4",
    "rr_9b41d5",
    "rr_9b41d6",
    "rr_9b41d2",
]

CONCRETE_ID_RE = re.compile(
    r"\b(?:INC|CHG|LOCK|TEL|CGH|CASE|RB|PM|COMMIT)-"
    r"(?:LIVE-\d+|[A-F0-9]{8}(?:-\d+)?|\d{3,}(?:-\d+)?)\b",
    re.IGNORECASE,
)
TERM_RE = re.compile(
    "|".join(re.escape(term) for term in NUMERAL_DENYLIST + RECEIPT_DENYLIST)
)


def _iter_bundle_files(bundle: Path):
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    bundle = root / BUNDLE_DIR
    if not bundle.is_dir():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{BUNDLE_DIR} not built; run the frontend build before this gate",
        )

    files = list(_iter_bundle_files(bundle))
    if not files:
        return finish(GATE_ID, BLOCKED, f"{BUNDLE_DIR} has no scannable assets")

    hits: list[tuple[str, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = str(path.relative_to(root))
        for match in TERM_RE.finditer(text):
            hits.append((relative, match.group(0)))
        for match in CONCRETE_ID_RE.finditer(text):
            hits.append((relative, match.group(0)))

    if not hits:
        return finish(
            GATE_ID,
            PASS,
            f"scanned {len(files)} bundle assets; no canned values or "
            "concrete participant IDs",
        )

    print("  canned values found in the built bundle:")
    for relative, term in sorted(set(hits)):
        print(f"    {relative}: {term}")
    return finish(
        GATE_ID,
        FAIL,
        f"{len(hits)} canned value occurrence(s) in the built frontend",
    )


if __name__ == "__main__":
    main_guard(run)
