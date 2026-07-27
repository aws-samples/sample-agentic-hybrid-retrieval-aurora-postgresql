from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import close_pool, get_conn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="+", required=True)
    args = parser.parse_args()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for file in args.files:
                print(f"Running {file}")
                cur.execute(Path(file).read_text(encoding="utf-8"))
    print("Done")

if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
