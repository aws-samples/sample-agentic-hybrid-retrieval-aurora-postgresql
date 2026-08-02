#!/usr/bin/env python3
"""G-11 - participant identity and live-only source lint.

Participant-facing source may contain run-derived placeholders, but it may not
compile a concrete incident, change, lock, telemetry, case, runbook, or
postmortem key. It also may not direct participants to retired seed or dump
workflows.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    repo_root,
)

GATE_ID = "G-11"
TITLE = "Live-only participant identity lint"

SCAN_ROOTS = [
    ".claude/skills",
    "agent",
    "backend/app",
    "backend/scripts",
    "frontend/src",
    "gates",
    "labs/exercises",
    "labs/incident",
    "lambda_mcp",
    "mcp-server/src",
    "scripts",
    "sql",
    "docs",
    "AGENTS.md",
    "HANDOFF.md",
    "README.md",
    "DAT410-BUILD-BRIEF.md",
    "WORKSHOP-BUILD-SUMMARY.md",
]

SKIP_DIR_NAMES = {
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    ".git",
    ".pytest_cache",
    "superpowers",
}

SKIP_FILES = {
    "docs/live-data-audit.md",
    "gates/noun_lint.py",
}

SCAN_SUFFIXES = {
    ".py",
    ".sql",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".md",
    ".sh",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    "",
}

CONCRETE_ID_RE = re.compile(
    r"\b(?:INC|CHG|LOCK|TEL|CGH|CASE|RB|PM|COMMIT)-"
    r"(?:LIVE-\d+|\d{3,}(?:-\d+)?)\b",
    re.IGNORECASE,
)

RETIRED_TERMS = (
    "make seed-local",
    "make seed-project",
    "fixture_payload.json",
    "hybrid-retrieval-seed-v2.dump",
)


def _iter_files(root: Path, base: Path):
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if str(path.relative_to(base)) in SKIP_FILES:
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        yield path


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    violations: list[tuple[str, int, str]] = []
    files_scanned = 0

    for entry in SCAN_ROOTS:
        for path in _iter_files(root / entry, root):
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                for match in CONCRETE_ID_RE.finditer(line):
                    violations.append(
                        (str(path.relative_to(root)), line_number, match.group(0))
                    )
                lowered = line.lower()
                for term in RETIRED_TERMS:
                    if term.lower() in lowered:
                        violations.append(
                            (str(path.relative_to(root)), line_number, term)
                        )

    if not violations:
        return finish(
            GATE_ID,
            PASS,
            f"scanned {files_scanned} participant files; identifiers are "
            "run-derived and no retired seed command is reachable",
        )

    print("  fixed participant identity or retired source path found:")
    for path, line_number, token in violations:
        print(f"    {path}:{line_number}: {token}")
    return finish(
        GATE_ID,
        FAIL,
        f"{len(violations)} live-only naming violation(s)",
    )


if __name__ == "__main__":
    main_guard(run)
