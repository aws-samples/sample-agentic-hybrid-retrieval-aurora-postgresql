"""Where each lab's exercise file and its reference answer live."""

from __future__ import annotations

import subprocess
from pathlib import Path

LAB1_SQL = Path("labs/lab1_retrieve/hybrid_search.sql")
LAB2_SQL = Path("labs/lab2_rank/rrf_contribution.sql")
LAB3_AGENT = Path("labs/lab3_reason/agent.py")
LAB_FILES: dict[int, Path] = {1: LAB1_SQL, 2: LAB2_SQL, 3: LAB3_AGENT}


def solution_path(exercise: Path) -> Path:
    """The reference answer kept beside an exercise file."""
    return exercise.parent / "solution" / exercise.name


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )


def shipped_text(relative: Path, root: Path) -> str:
    """A lab file's text from the checkout, or Git's copy when a participant deleted it.

    The workshop checkout is the pinned source revision and refuses participant
    commits, so `HEAD` holds every lab file the source ships, reference answers
    included.

    Raises:
        FileNotFoundError: When the file is gone and Git holds no copy of it.
    """
    path = root / relative
    if path.exists():
        return path.read_text(encoding="utf-8")
    shown = _git(root, "show", f"HEAD:{relative.as_posix()}")
    if shown.returncode != 0:
        raise FileNotFoundError(
            f"Lab file rule: {relative} is missing and Git holds no copy of it; fix: "
            "ask your facilitator to restore it from the workshop source."
        )
    return shown.stdout.decode("utf-8")


def shipped_files(folder: Path, root: Path) -> list[Path]:
    """Every file the source ships in a lab folder, whether or not it is on disk.

    Raises:
        FileNotFoundError: When Git cannot list the folder.
    """
    listed = _git(
        root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", folder.as_posix()
    )
    if listed.returncode != 0:
        raise FileNotFoundError(
            f"Lab file rule: Git cannot list {folder}; fix: ask your facilitator to "
            "restore it from the workshop source."
        )
    return [Path(name) for name in listed.stdout.decode("utf-8").split("\0") if name]
