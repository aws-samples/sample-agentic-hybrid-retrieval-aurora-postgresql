from pathlib import Path
from shutil import copy2

import pytest

from scripts.lab_state import (
    LABS,
    REPO,
    lab_is_solved,
    set_isolated_lab_state,
    set_lab_state,
)


@pytest.fixture
def lab_repo(tmp_path: Path) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


def _lab_bytes(repo: Path) -> dict[str, bytes]:
    return {
        relative_path: (repo / relative_path).read_bytes()
        for relative_path in {definition[0] for definition in LABS.values()}
    }


@pytest.mark.parametrize("lab", sorted(LABS))
def test_reset_and_solution_are_idempotent(lab_repo: Path, lab: int) -> None:
    set_isolated_lab_state(lab, repo=lab_repo)
    first_reset = _lab_bytes(lab_repo)
    set_isolated_lab_state(lab, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_reset
    assert not lab_is_solved(lab, repo=lab_repo)
    assert all(
        lab_is_solved(candidate, repo=lab_repo)
        for candidate in LABS
        if candidate != lab
    )

    set_lab_state(lab, solved=True, repo=lab_repo)
    first_solution = _lab_bytes(lab_repo)
    set_lab_state(lab, solved=True, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_solution
    assert all(lab_is_solved(candidate, repo=lab_repo) for candidate in LABS)
