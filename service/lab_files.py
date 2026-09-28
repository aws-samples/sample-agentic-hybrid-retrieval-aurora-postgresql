"""Where each lab's exercise file and its reference answer live."""

from __future__ import annotations

from pathlib import Path

LAB1_SQL = Path("labs/lab1_retrieve/hybrid_search.sql")
LAB2_SQL = Path("labs/lab2_rank/rrf_contribution.sql")
LAB3_AGENT = Path("labs/lab3_reason/agent.py")
LAB_FILES: dict[int, Path] = {1: LAB1_SQL, 2: LAB2_SQL, 3: LAB3_AGENT}


def solution_path(exercise: Path) -> Path:
    """The reference answer kept beside an exercise file."""
    return exercise.parent / "solution" / exercise.name
