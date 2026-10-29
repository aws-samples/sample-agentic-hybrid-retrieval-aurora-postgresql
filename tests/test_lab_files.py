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


def test_git_missing_from_the_path_is_named_not_a_bare_file_not_found(
    shipped_labs: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory
) -> None:
    reference = solution_path(LAB_FILES[1])
    (shipped_labs / reference).unlink()
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("no-git")))

    with pytest.raises(FileNotFoundError, match="git is not installed or not on PATH"):
        shipped_text(reference, shipped_labs)


def test_a_checkout_without_git_history_says_what_git_answered(
    shipped_labs: Path,
) -> None:
    reference = solution_path(LAB_FILES[1])
    (shipped_labs / reference).unlink()
    rmtree(shipped_labs / ".git")

    with pytest.raises(FileNotFoundError) as refused:
        shipped_text(reference, shipped_labs)

    message = str(refused.value)
    assert "not a git repository" in message
    assert "Git holds no copy" not in message
    assert str(shipped_labs) not in message


def test_git_cannot_list_a_folder_without_history(shipped_labs: Path) -> None:
    rmtree(shipped_labs / ".git")

    with pytest.raises(
        FileNotFoundError, match="Git cannot list labs/lab1_retrieve .*not a git repo"
    ):
        shipped_files(LAB_FILES[1].parent, shipped_labs)


def test_a_git_that_hangs_is_stopped_and_named(
    shipped_labs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    def hang(command, **options):
        assert options["timeout"] == 30
        raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)

    with pytest.raises(FileNotFoundError, match="did not answer within 30 seconds"):
        shipped_files(LAB_FILES[1].parent, shipped_labs)


def test_a_checkout_below_the_git_root_reads_files_the_way_it_lists_them(
    shipped_labs: Path, tmp_path_factory
) -> None:
    """`git show HEAD:path` is repository-relative; `ls-tree` is directory-relative."""
    import subprocess

    outer = tmp_path_factory.mktemp("outer")
    inner = outer / "checkout"
    inner.mkdir()
    for name in ("labs",):
        subprocess.run(["cp", "-R", str(shipped_labs / name), str(inner)], check=True)
    git = ["git", "-C", str(outer), "-c", "user.name=t", "-c", "user.email=t@e.x"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "ship"], check=True)
    reference = solution_path(LAB_FILES[1])
    expected = (inner / reference).read_text(encoding="utf-8")
    (inner / reference).unlink()

    assert reference in shipped_files(LAB_FILES[1].parent, inner)
    assert shipped_text(reference, inner) == expected


def test_the_shipped_labs_fixture_holds_what_head_ships_not_the_working_tree(
    shipped_labs: Path,
) -> None:
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    names = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD", "--", "labs"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert names

    for name in names:
        shipped = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{name}"],
            check=True,
            capture_output=True,
        ).stdout
        assert (shipped_labs / name).read_bytes() == shipped, name
