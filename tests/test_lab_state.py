from pathlib import Path

import pytest

from scripts.lab_state import (
    LABS,
    lab_is_solved,
    set_isolated_lab_state,
    set_lab_state,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("lab", sorted(LABS))
def test_each_lab_reset_is_red_and_solution_is_byte_identical(tmp_path, lab):
    originals: dict[Path, bytes] = {}
    for relative_name, _ in LABS.values():
        relative_path = Path(relative_name)
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        originals[relative_path] = (REPO / relative_path).read_bytes()
        target.write_bytes(originals[relative_path])

    set_isolated_lab_state(lab, repo=tmp_path)
    assert not lab_is_solved(lab, repo=tmp_path)
    assert all(
        lab_is_solved(other, repo=tmp_path)
        for other in LABS
        if other != lab
    )

    set_lab_state(lab, solved=True, repo=tmp_path)
    assert all(lab_is_solved(other, repo=tmp_path) for other in LABS)
    for relative_path, original in originals.items():
        assert (tmp_path / relative_path).read_bytes() == original


def test_resetting_next_lab_restores_previous_lab_prerequisites(tmp_path):
    for relative_path, _ in LABS.values():
        source = REPO / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    set_isolated_lab_state(1, repo=tmp_path)
    assert not lab_is_solved(1, repo=tmp_path)
    assert lab_is_solved(2, repo=tmp_path)
    assert lab_is_solved(3, repo=tmp_path)

    set_isolated_lab_state(2, repo=tmp_path)
    assert lab_is_solved(1, repo=tmp_path)
    assert not lab_is_solved(2, repo=tmp_path)
    assert lab_is_solved(3, repo=tmp_path)

    set_isolated_lab_state(3, repo=tmp_path)
    assert lab_is_solved(1, repo=tmp_path)
    assert lab_is_solved(2, repo=tmp_path)
    assert not lab_is_solved(3, repo=tmp_path)
