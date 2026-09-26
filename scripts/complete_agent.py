"""Save the participant's selected Mosaic run and check the deployed agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from scripts import lab_exercise


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=UUID, required=True)
    args = parser.parse_args()
    output = ROOT / ".local/lab-3"
    output.mkdir(parents=True, exist_ok=True)
    values = {"lab_agent_id": str(args.run_id)}
    (output / "context.json").write_text(json.dumps(values) + "\n")
    (output / "context.psql").write_text(f"\\set lab_agent_id '{args.run_id}'\n")
    sys.argv = [sys.argv[0], "check", "--lab", "3"]
    return lab_exercise.main()


if __name__ == "__main__":
    raise SystemExit(main())
