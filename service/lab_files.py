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


GIT_TIMEOUT_SECONDS = 30


def _git(root: Path, *args: str) -> tuple[bytes | None, str]:
    """Git's output, or None and why it failed, in words that name no absolute path."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return None, f"git did not answer within {GIT_TIMEOUT_SECONDS} seconds"
    except OSError as error:
        return None, f"git could not run: {error.strerror or type(error).__name__}"
    if done.returncode == 0:
        return done.stdout, ""
    lines = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
    first = lines[0] if lines else f"git exited with status {done.returncode}"
    return None, first.replace(str(root), ".")


def committed_text(relative: Path, root: Path) -> str:
    """A lab file's text as Git's `HEAD` holds it, whatever is on disk.

    The path is read relative to `root`, as `shipped_files` lists it, so a checkout
    whose lab folders sit below the Git root still finds them.

    Raises:
        FileNotFoundError: When Git cannot give the file.
    """
    shown, reason = _git(root, "show", f"HEAD:./{relative.as_posix()}")
    if shown is None:
        raise FileNotFoundError(
            f"Lab file rule: {relative} is missing and Git gave no copy ({reason}); "
            "fix: ask your facilitator to restore it from the workshop source."
        )
    return shown.decode("utf-8")


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
    return committed_text(relative, root)


def shipped_files(folder: Path, root: Path) -> list[Path]:
    """Every file the source ships in a lab folder, whether or not it is on disk.

    Raises:
        FileNotFoundError: When Git cannot list the folder.
    """
    listed, reason = _git(
        root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", folder.as_posix()
    )
    if listed is None:
        raise FileNotFoundError(
            f"Lab file rule: Git cannot list {folder} ({reason}); fix: ask your "
            "facilitator to restore it from the workshop source."
        )
    return [Path(name) for name in listed.decode("utf-8").split("\0") if name]
