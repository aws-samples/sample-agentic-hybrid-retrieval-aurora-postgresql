"""`service.models` must import without a database driver.

The packaged MCP adapter (`mcp-server/mcp_tests/contract_cases.py`) compares its
wire contract against these classes from an isolated environment that has no
`psycopg`. On 2026-09-04 Project CI failed because `service.models` imported
`service.coverage`, which imports `psycopg` and `service.db` at module level.
The coverage response models now live in `service.models`, and this test keeps
the chain closed: it re-imports `service.models` in a subprocess whose import
hook refuses `psycopg`, so the guard cannot be satisfied by the driver merely
being installed in the test environment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GUARDED_IMPORT = """
import builtins
real_import = builtins.__import__
def refuse_psycopg(name, *args, **kwargs):
    if name == "psycopg" or name.startswith("psycopg."):
        raise ImportError(f"{name} imported by the service.models chain")
    return real_import(name, *args, **kwargs)
builtins.__import__ = refuse_psycopg
import service.models
print("ok")
"""


def test_service_models_imports_without_psycopg() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", GUARDED_IMPORT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        "Rule: service.models must not import psycopg, directly or "
        "transitively, because the packaged MCP adapter imports it from an "
        f"environment without a database driver. Found: {completed.stderr.strip()}. "
        "Fix: keep response models in service.models and import database "
        "helpers only inside the modules that need them."
    )
    assert completed.stdout.strip() == "ok"
