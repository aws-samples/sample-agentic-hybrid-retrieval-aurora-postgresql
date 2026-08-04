#!/usr/bin/env python3
"""Preload the disposable operational workload without creating evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from labs.incident.run_live_workshop import (
    LiveWorkshopError,
    prepare_lab_workload,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create 5,000 workbench_lab customers and 25,000 orders while "
            "preserving an empty participant evidence store."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        required=os.getenv("DATABASE_URL") is None,
    )
    args = parser.parse_args()
    try:
        state = prepare_lab_workload(args.database_url)
    except (LiveWorkshopError, psycopg.Error) as error:
        print(f"WORKLOAD PREPARATION FAILED: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "ready",
                "relations": [
                    "workbench_lab.customers",
                    "workbench_lab.orders",
                ],
                **state,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
