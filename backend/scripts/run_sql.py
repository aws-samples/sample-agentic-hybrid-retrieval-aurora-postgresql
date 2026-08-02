from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import close_pool, get_owner_conn


def run_sql_files(conn, files: Iterable[str | Path]) -> list[Path]:
    """Apply the selected SQL files as one all-or-nothing transaction."""
    paths = [Path(file) for file in files]
    applied: list[Path] = []
    active_path: Path | None = None
    phase = "starting transaction"

    try:
        with conn.transaction():
            phase = "opening cursor"
            with conn.cursor() as cur:
                for path in paths:
                    active_path = path
                    phase = f"applying {path}"
                    print(f"Running {path}")
                    cur.execute(path.read_text(encoding="utf-8"))
                    applied.append(path)
                    print(f"Executed {path}; pending transaction commit")
            active_path = None
            phase = "committing selected SQL set"
    except Exception as error:
        target = f" while applying {active_path}" if active_path else ""
        print(
            f"SQL migration failed{target}; rolled back selected SQL set "
            f"({phase}): {error}",
            file=sys.stderr,
        )
        raise

    print(f"Committed {len(applied)} SQL file(s) in one transaction")
    return applied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="+", required=True)
    args = parser.parse_args()
    with get_owner_conn() as conn:
        run_sql_files(conn, args.files)
    print("Done")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
