"""Shared helpers for the DAT410 gate harness.

Every gate is a standalone script that exits with one of three codes so the
orchestrator (`checks.sh`) and CI can tell the difference between a real defect
and a not-yet-built dependency:

* ``PASS`` (0)    - the gate ran and its assertions held.
* ``FAIL`` (1)    - the gate ran and an assertion failed. This is a defect to fix.
* ``BLOCKED`` (2) - the subject under test does not exist yet (for example the
  ``_verify_sql`` registry or ``agent/registry.py``). Reported honestly; never
  counted as a pass.

Gates never write to or run DDL against any database. Database-backed gates open
a read-only session (``SELECT`` / ``SET LOCAL`` only) against the ``DATABASE_URL``
already configured for the repo.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

PASS = 0
FAIL = 1
BLOCKED = 2

_STATUS_LABEL = {PASS: "PASS", FAIL: "FAIL", BLOCKED: "BLOCKED"}


def repo_root() -> Path:
    """Return the repository root (the parent of the ``gates/`` directory)."""
    return Path(__file__).resolve().parents[1]


def status_label(code: int) -> str:
    """Return the human label for an exit code."""
    return _STATUS_LABEL.get(code, f"UNKNOWN({code})")


def print_header(gate_id: str, title: str) -> None:
    """Print a gate banner to stdout."""
    print(f"=== {gate_id} - {title} ===")


def finish(gate_id: str, code: int, summary: str) -> int:
    """Print the terminal status line for a gate and return its exit code."""
    print(f"[{status_label(code)}] {gate_id}: {summary}")
    return code


def read_env_value(name: str) -> str | None:
    """Resolve an environment variable, falling back to the repo ``.env`` file.

    The value is never printed. Credentials embedded in ``DATABASE_URL`` stay in
    memory only; callers must redact before logging.
    """
    import os

    value = os.environ.get(name)
    if value:
        return value
    env_path = repo_root() / ".env"
    if not env_path.exists():
        return None
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=\s*(.*)$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        return raw
    return None


def redact_dsn(dsn: str) -> str:
    """Return ``dsn`` with any ``user:password@`` credentials masked."""
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", dsn)


def require(condition: bool, message: str) -> None:
    """Raise :class:`AssertionError` with ``message`` when ``condition`` is false."""
    if not condition:
        raise AssertionError(message)


def main_guard(run) -> None:
    """Run ``run`` and translate uncaught errors into a FAIL exit.

    ``run`` returns an exit code. A raised :class:`AssertionError` becomes a FAIL
    so a gate can assert with plain ``require`` calls.
    """
    try:
        sys.exit(run())
    except AssertionError as exc:
        print(f"assertion failed: {exc}")
        sys.exit(FAIL)
