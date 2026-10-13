#!/usr/bin/env python3
"""Show which lines of your lab files differ from the reference answer, in plain words.

usage: uv run python scripts/diff.py [FILE] [--answer]

With no FILE, every lab file is checked and only the ones that differ are shown; a
lab you have not started still matches, so normally only your current lab appears.
Give a lab file's path or name, such as hybrid_search.sql, to check just that one.
Inside the marked blocks it names your lines that differ but hides the answer; add
--answer to see the reference answer's lines too. Outside the markers it compares
with the original file, so an edit that drifted outside them shows. Nothing is
changed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lab_state import LABS, REPO, lab_diff


def lab_for(name: str) -> int:
    """The lab whose exercise file a path or file name names."""
    wanted = Path(name)
    for lab, (relative_path, _blocks) in LABS.items():
        path = Path(relative_path)
        if wanted == path or wanted.name == path.name and len(wanted.parts) == 1:
            return lab
    files = ", ".join(path for path, _blocks in LABS.values())
    raise ValueError(
        f"Diff rule: {name} is not a lab file; fix: name one of {files}, or none"
    )


def report(
    name: str | None = None,
    *,
    repo: Path = REPO,
    color: bool = False,
    answer: bool = False,
) -> str:
    """The plain-words report for one lab file, or for every lab file that differs."""
    labs = [lab_for(name)] if name else sorted(LABS)
    sections = []
    for lab in labs:
        text, differs = lab_diff(lab, repo=repo, color=color, answer=answer)
        if differs or name:
            sections.append(text)
    if not sections:
        return "Every lab file matches the reference answer, inside and outside the markers."
    return "\n\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "file", nargs="?", help="a lab file's path or name; default: every lab file"
    )
    parser.add_argument(
        "--answer", action="store_true", help="also print the reference answer's lines"
    )
    args = parser.parse_args()
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    try:
        print(report(args.file, color=color, answer=args.answer))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
