"""A shipped lab file a participant deleted is read from Git's copy, never guessed."""

from __future__ import annotations

from pathlib import Path
from shutil import rmtree

import pytest

from service.lab_files import LAB_FILES, shipped_files, shipped_text, solution_path


@pytest.mark.parametrize("lab", sorted(LAB_FILES))
def test_a_deleted_lab_folder_is_read_back_from_git(
    shipped_labs: Path, lab: int
) -> None:
    reference = solution_path(LAB_FILES[lab])
    expected = (shipped_labs / reference).read_text(encoding="utf-8")
    rmtree(shipped_labs / LAB_FILES[lab].parent)

    assert shipped_text(reference, shipped_labs) == expected
    assert LAB_FILES[lab] in shipped_files(LAB_FILES[lab].parent, shipped_labs)
    assert reference in shipped_files(LAB_FILES[lab].parent, shipped_labs)


def test_a_file_on_disk_is_read_from_disk(shipped_labs: Path) -> None:
    exercise = LAB_FILES[1]
    (shipped_labs / exercise).write_text(
        "-- the participant's edit\n", encoding="utf-8"
    )

    assert shipped_text(exercise, shipped_labs) == "-- the participant's edit\n"


def test_a_file_git_never_held_names_the_rule_and_the_fix(tmp_path: Path) -> None:
    with pytest.raises(
        FileNotFoundError, match="Lab file rule: .* ask your facilitator"
    ):
        shipped_text(solution_path(LAB_FILES[1]), tmp_path)
