"""The deploy record tolerates mixed timestamps and concurrent writers."""

import json
import threading
import time
from datetime import UTC, datetime

import pytest

from service import agent_deploys
from service.agent_deploys import (
    deploys_path,
    load_deploys,
    record_deploy,
    reference_agent_notice,
)


def _write(rows):
    path = deploys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))


def _row(at: str, sha: str = "a" * 64):
    return {"deployed_at": at, "runtime_version": "1", "application_sha256": sha}


def test_a_naive_timestamp_among_aware_ones_does_not_raise():
    _write([_row("2026-10-25T10:00:00+00:00"), _row("2026-10-25T09:00:00")])
    deploys = load_deploys()
    assert [d.deployed_at.hour for d in deploys] == [9, 10]
    assert all(d.deployed_at.tzinfo is not None for d in deploys)


def test_a_naive_now_is_recorded_as_utc():
    deploy = record_deploy("1", "b" * 64, now=datetime(2026, 10, 25, 9, 0))  # noqa: DTZ001 - naive on purpose
    assert deploy.deployed_at == datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def test_concurrent_deploys_all_survive_and_leave_no_temporary_file(monkeypatch):
    """Falsifier: an unlocked read-modify-write loses all but the last of these."""
    real_load = agent_deploys.load_deploys

    def slow_load(root=None):
        earlier = real_load(root)
        time.sleep(0.02)
        return earlier

    monkeypatch.setattr(agent_deploys, "load_deploys", slow_load)
    threads = [
        threading.Thread(target=record_deploy, args=(str(n), f"{n:064d}"))
        for n in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(d.runtime_version for d in real_load()) == [str(n) for n in range(8)]
    assert not list(deploys_path().parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "content", ["[]", '{"version": 1, "lab": 3, "completed_at": 5}', "{not json"]
)
def test_an_unreadable_lab_3_start_record_names_the_reset(content):
    path = agent_deploys.ROOT / ".local" / "lab-3" / "start.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    with pytest.raises(ValueError, match=r"lab_state\.py reset --lab 3"):
        reference_agent_notice()
