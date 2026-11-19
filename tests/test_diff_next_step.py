"""`diff.py` names the deploy as Lab 3's next step once nothing differs and Runtime is stale."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import diff
from service import agent_deploys
from service.lab_validation_receipt import application_digest
from service.participant_commands import DEPLOY_AGENT, STATUS

STARTED = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def lab_3_workspace(tmp_path, monkeypatch):
    """A workspace of its own, so each test writes its own start and deploy records."""
    monkeypatch.setattr(agent_deploys, "ROOT", tmp_path)
    return tmp_path


def _start_lab_3(root) -> None:
    path = root / ".local" / "lab-3" / "start.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "lab": 3,
                "steps": {},
                "completed_at": STARTED.isoformat(),
            }
        )
    )


def _deploy(sha: str, *, after: timedelta = timedelta(minutes=5)) -> None:
    agent_deploys.record_deploy("2", sha, now=STARTED + after)


def _next_line(monkeypatch, capsys) -> str:
    monkeypatch.setattr("sys.argv", ["diff.py"])
    assert diff.main() == 0
    return capsys.readouterr().out.rstrip().splitlines()[-1]


def test_nothing_differs_and_no_deploy_since_lab_3_started_names_the_deploy(
    lab_3_workspace, monkeypatch, capsys
):
    _start_lab_3(lab_3_workspace)

    assert _next_line(monkeypatch, capsys) == DEPLOY_AGENT


def test_nothing_differs_and_code_changed_after_the_deploy_names_the_deploy(
    lab_3_workspace, monkeypatch, capsys
):
    _start_lab_3(lab_3_workspace)
    _deploy("0" * 64)

    assert _next_line(monkeypatch, capsys) == DEPLOY_AGENT


def test_nothing_differs_and_deployed_with_this_code_keeps_the_status_step(
    lab_3_workspace, monkeypatch, capsys
):
    _start_lab_3(lab_3_workspace)
    _deploy(application_digest())

    assert _next_line(monkeypatch, capsys) == STATUS


def test_nothing_differs_before_lab_3_starts_keeps_the_status_step(monkeypatch, capsys):
    assert _next_line(monkeypatch, capsys) == STATUS


def _lab_2_with_kept_todo(repo, code: str | None = None) -> None:
    """The smallest repair: the starter's two TODO lines stay beside the answer's code."""
    from scripts.lab_state import LAB2_STARTER, LABS, _replace_block

    path = repo / LABS[2][0]
    start, end, fixed, _broken = LABS[2][1][0]
    todo = "\n".join(LAB2_STARTER.splitlines()[:2])
    path.write_text(
        _replace_block(path.read_text(), start, end, f"{todo}\n{code or fixed}")
    )


def test_kept_todo_comments_are_reported_as_comment_only_not_as_a_difference(
    tmp_path, monkeypatch, capsys
):
    from shutil import copy2

    from scripts.lab_state import LABS, REPO, lab_diff, lab_source_is_repaired

    for relative_path in {definition[0] for definition in LABS.values()}:
        (tmp_path / relative_path).parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, tmp_path / relative_path)
    _lab_2_with_kept_todo(tmp_path)
    assert lab_source_is_repaired(2, repo=tmp_path)

    report, differs = lab_diff(2, repo=tmp_path)
    answer, _ = lab_diff(2, repo=tmp_path, answer=True)

    assert differs
    assert "only comment lines differ" in report
    assert "(comment lines only)" in report
    assert "TODO(Lab 2)" in report
    assert "where your" not in report
    assert "Apply:" not in report and "apply-solution" not in report
    assert "only comment lines differ" in answer

    monkeypatch.setattr("scripts.diff.REPO", tmp_path)
    monkeypatch.setattr(diff, "report", lambda *a, **k: report)
    monkeypatch.setattr(diff, "differing_lab", lambda *a, **k: 2)
    monkeypatch.setattr(diff, "comment_only_difference", lambda lab: True)
    monkeypatch.setattr("sys.argv", ["diff.py"])
    assert diff.main() == 0
    out = capsys.readouterr().out
    assert "only comment lines differ, so there is nothing to change" in out
    assert out.rstrip().splitlines()[-1] == STATUS


def test_a_different_line_beside_kept_comments_is_still_a_difference(tmp_path):
    from shutil import copy2

    from scripts.lab_state import LABS, REPO, lab_diff

    for relative_path in {definition[0] for definition in LABS.values()}:
        (tmp_path / relative_path).parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, tmp_path / relative_path)
    _lab_2_with_kept_todo(tmp_path, "SELECT 1.0 / (rrf_k + source_rank)")

    report, differs = lab_diff(2, repo=tmp_path)

    assert differs
    assert "where your" in report
    assert "only comment lines differ" not in report
    assert "Apply:" in report


def test_an_edit_outside_the_markers_names_the_line_and_the_apply_step_not_reset(
    tmp_path,
):
    from shutil import copy2

    from scripts.lab_state import LABS, REPO, lab_diff
    from service.participant_commands import APPLY_SQL

    for relative_path in {definition[0] for definition in LABS.values()}:
        (tmp_path / relative_path).parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, tmp_path / relative_path)
    path = tmp_path / LABS[1][0]
    path.write_text(
        path.read_text().replace(
            "result_limit integer DEFAULT 50", "result_limit integer DEFAULT 1"
        )
    )

    report, differs = lab_diff(1, repo=tmp_path)

    assert differs
    assert "Outside the markers, at line 31 of your file" in report
    assert "result_limit integer DEFAULT 50" in report
    assert APPLY_SQL in report
    assert "reset" not in report and "start over" not in report


def test_comment_and_spacing_edits_outside_the_markers_are_not_a_difference(tmp_path):
    from shutil import copy2

    from scripts.lab_state import LABS, REPO, lab_diff

    for relative_path in {definition[0] for definition in LABS.values()}:
        (tmp_path / relative_path).parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, tmp_path / relative_path)
    path = tmp_path / LABS[1][0]
    path.write_text(
        path.read_text().replace(
            "    fuzzy_threshold real DEFAULT 0.20",
            "    -- my note\n    fuzzy_threshold  real  DEFAULT 0.20",
        )
    )

    assert lab_diff(1, repo=tmp_path)[1] is False
