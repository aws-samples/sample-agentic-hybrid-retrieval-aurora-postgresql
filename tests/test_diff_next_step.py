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
        json.dumps({"version": 1, "lab": 3, "completed_at": STARTED.isoformat()})
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
