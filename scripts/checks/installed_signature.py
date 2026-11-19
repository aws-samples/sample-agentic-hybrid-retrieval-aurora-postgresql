"""Print each lab function's installed parameters beside the saved file's, and the verdict.

Read-only: one `pg_get_functiondef` read per lab, no writes. Run it on a prepared
terminal to confirm how Aurora prints parameter defaults (`0.20` on a `real` parameter,
`vector(1024)`) and that the comparison `status` uses reads them as the file's:

    env PYTHONPATH=. uv run python scripts/checks/installed_signature.py

Exits 1 when a lab's installed parameters differ from its saved file's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg.rows import dict_row

from scripts.lab_state import (
    LABS,
    RRF_CONTRIBUTION_FUNCTION,
    parameter_list,
    signature_problem,
)
from service.catalog_runtime import search_schema
from service.search_sql import FUSED_DEFINITION_SQL, FUSED_FUNCTION


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is empty; open a terminal that loads it.")
    functions = {
        1: f"{search_schema()}.{FUSED_FUNCTION}",
        2: f"{search_schema()}.{RRF_CONTRIBUTION_FUNCTION}",
    }
    failed = False
    with psycopg.connect(url, connect_timeout=20, row_factory=dict_row) as connection:
        for lab, function in functions.items():
            row = connection.execute(FUSED_DEFINITION_SQL, (function,)).fetchone()
            installed = row["definition"]
            saved = (ROOT / LABS[lab][0]).read_text(encoding="utf-8")
            print(f"Lab {lab}: {function}")
            print(f"  installed: {parameter_list(installed) if installed else None}")
            print(f"  saved:     {parameter_list(saved)}")
            problem = (
                "Aurora has no such function"
                if installed is None
                else signature_problem(installed, saved)
            )
            print(
                f"  verdict:   {'SAME' if problem is None else 'DIFFERENT: ' + problem}"
            )
            failed = failed or problem is not None
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
