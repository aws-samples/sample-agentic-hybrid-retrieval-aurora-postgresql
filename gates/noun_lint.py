#!/usr/bin/env python3
"""G-11 - Law 1 noun lint.

SPEC-session Section 10, G-11: grep across guide/scripts/fixtures for a
canonical-noun list; any synonym fails CI.

Law 1 (SPEC-session Section 0): the live schema, the corpus fixtures, the guide,
and the UI use identical identifiers. The canonical thread is
``CHG-1842`` / ``INC-2047`` / ``CGH-1842`` / ``checkout-prod-cluster-01`` and the
evidence keys in the implementation spec Section 4. Any new name is a defect.

This gate is a denylist scanner. The denylist is the exact set of
de-canonicalized round-number substitutes recorded in
``design/verity/fixtures/id-migration.json`` (its right-hand column), plus the
D14-banned digit-transposition ``CHG-1482`` and the truncated cluster name. When
the corpus is re-nouned to the canonical thread (Step 1), every hit disappears
and this gate goes green.

Background filler identifiers (``MNT-BG-*``, ``INC-BG-*``, ``CASE-BG-*``,
``Tenant-*``) are deliberately generic and are not canonical-thread synonyms, so
they are not flagged.
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
TITLE = "Law 1 noun lint"

# Top-level repo entries that ship in the lab surface. ``design/`` is the spec
# workspace: it holds the migration map and intentional negative examples
# (``CHG-1482`` as the banned tie), so it is never scanned.
SCAN_ROOTS = [
    "seed",
    "sql",
    "backend",
    "frontend/src",
    "scripts",
    "docs",
    "mcp-server/src",
    "lambda_mcp",
    ".claude/skills",
    "guide",
    "AGENTS.md",
    "README.md",
    "CLAUDE.md",
    "SECURITY_REVIEW.md",
    "Makefile",
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
    "",  # Makefile and other extension-less sources
}

# Exact de-canonicalized substitutes (id-migration.json right-hand column) plus
# the D14-banned digit transposition. Each maps to the canonical noun it
# displaced, so the failure message points at the fix.
SYNONYM_TO_CANONICAL = {
    "CHG-1000": "CHG-1842",
    "CHG-1001": "CHG-1838",
    "CHG-1002": "CHG-1907",
    "CHG-1010": "CHG-1731",
    "CHG-1011": "CHG-1731 (staging rehearsal has no canonical key; re-scope)",
    "INC-2000": "INC-2047",
    "INC-2001": "INC-1980",
    "INC-2010": "INC-1980 (staging look-alike has no canonical key; re-scope)",
    "LOCK-3000": "LOCK-2047-001",
    "LOCK-3001": "LOCK-2047-002",
    "CASE-4000": "CASE-7419",
    "CASE-4001": "CASE-7421",
    "CASE-4002": "CASE-7424",
    "RB-5000": "RB-017",
    "RB-5001": "RB-092",
    "COMMIT-6000": "COMMIT-4471",
    "PM-9000": "PM-2047 (postmortem key; assign a canonical irregular number)",
    "CGH-1000": "CGH-1842",
    "CHG-1482": "CGH-1842 (D14: digit transposition is a six-way tie and is banned)",
    "checkout-prod-01": "checkout-prod-cluster-01",
    "checkout_orders": "shop.orders",
    "cust_id": "customer_id",
}

# A round-number canonical-thread ID that is not in the explicit map above still
# violates D14 ("no CHG-1000-style rounds"). Background filler (``*-BG-*``) is
# excluded by the negative lookahead.
ROUND_NUMBER_RE = re.compile(
    r"\b(?:CHG|INC|CASE|RB|COMMIT|PM|LOCK)-(?!BG-)\d*0{3}\b"
)

# A7 vocabulary collapse: one identity axis, the persona. These tokens named the
# retired second axis. Anchored so acl_principals / p_principal / pg_has_role and
# the RLS predicate's own text are not hits: only the bare participant-facing
# nouns are banned.
BANNED_IDENTITY_RE = re.compile(
    r"(?<![\w.\-])(?:support-lead|support_lead)(?![\w\-])"
    r"|(?<![\w.\-_])principal(?![\w\-_])"
)

# Lines that legitimately carry a banned token: the RLS/ACL predicate path keeps
# acl_principals and the p_principal parameter until the wire rename lands, this
# gate's own source names the tokens it bans, sql/01_schema.sql's pre-collapse
# migration reads and drops the old `principal` column and its `support-lead`
# value by name (the tokens *are* the pre-collapse column and value -- renaming
# them breaks the migration), sql/04_diagnostics.sql:441 explains why the view
# is dropped before replace in terms of the old column, and two negative tests
# (test_db_persona.py, test_verify_sql.py) pass "support-lead" as rejected input
# to prove the collapse is enforced. Each pattern below is anchored to one exact
# idiom, not a blanket exemption for "principal" or "support-lead".
BANNED_IDENTITY_ALLOW = re.compile(
    r"acl_principals|p_principal|BANNED_IDENTITY|required_principals"
    r"|column_name = 'principal'"
    r"|DROP COLUMN principal"
    r"|'principals' \? 'support-lead'"
    r"|support-lead pair, which map onto"
    r"|support-lead saw the restricted row"
    r"|changed from principal jsonb to role text"
    r'|persona_role\("support-lead"\)'
    r'|receipt_verify_sql\([^)]*"support-lead"\)'
)


def _iter_files(root: Path, repo_root_path: Path):
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
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        # docs/superpowers/ holds design specs and implementation plans --
        # engineering history that must be free to name retired vocabulary in
        # order to explain why it was retired. Participant-facing docs (e.g.
        # docs/architecture.md) are one level up and stay scanned.
        rel_parts = path.relative_to(repo_root_path).parts
        if rel_parts[:2] == ("docs", "superpowers"):
            continue
        yield path


def _scan_line(line: str) -> list[tuple[str, str]]:
    """Return (token, canonical) hits for one line."""
    hits: list[tuple[str, str]] = []
    for synonym, canonical in SYNONYM_TO_CANONICAL.items():
        if re.search(rf"(?<![\w-]){re.escape(synonym)}(?![\w-])", line):
            hits.append((synonym, canonical))
    for match in ROUND_NUMBER_RE.finditer(line):
        token = match.group(0)
        if token not in SYNONYM_TO_CANONICAL:
            hits.append((token, "irregular canonical ID (D14: no round numbers)"))
    if BANNED_IDENTITY_RE.search(line) and not BANNED_IDENTITY_ALLOW.search(line):
        token = BANNED_IDENTITY_RE.search(line).group(0)
        hits.append((token, "the persona (analyst/admin/auditor); A7 retired this"))
    return hits


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    violations: list[tuple[str, int, str, str]] = []
    files_scanned = 0
    for entry in SCAN_ROOTS:
        for path in _iter_files(root / entry, root):
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = path.relative_to(root)
            for lineno, line in enumerate(text.splitlines(), start=1):
                for token, canonical in _scan_line(line):
                    violations.append((str(rel), lineno, token, canonical))

    if not violations:
        return finish(
            GATE_ID,
            PASS,
            f"scanned {files_scanned} files; no canonical-noun synonyms found",
        )

    by_token: dict[str, int] = {}
    for rel, lineno, token, canonical in violations:
        by_token[token] = by_token.get(token, 0) + 1
        print(f"  {rel}:{lineno}: {token} -> use {canonical}")

    print()
    print("  synonym counts (most frequent first):")
    for token, count in sorted(by_token.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {token}: {count}")

    return finish(
        GATE_ID,
        FAIL,
        f"{len(violations)} synonym hits across {len(by_token)} distinct tokens "
        f"in {files_scanned} scanned files",
    )


if __name__ == "__main__":
    main_guard(run)
