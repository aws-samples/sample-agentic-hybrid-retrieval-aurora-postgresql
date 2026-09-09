"""Saved run IDs must re-enter the live grading path, never cache PASS."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_lab_proof import _evidence_row, _grounded_connection

from scripts import validate_lab
from service import lab_checks, lab_proof
from service import lab_validation_receipt as receipt


@pytest.fixture
def saved_runs(monkeypatch):
    missions = [
        lab_checks.load_mission("reason"),
        lab_checks.load_case("evidence-grounding"),
    ]
    connections = {}
    run_ids = {}
    for mission in missions:
        run_id = uuid4()
        connection = _grounded_connection()
        connection.turn["agent_turn_id"] = run_id
        connection.turn["user_message"] = mission["query"]
        connection.turn["extracted_intent"]["outcome"] = "answered"
        for product in connection.turn["extracted_intent"]["selected_products"]:
            product["attributes"]["seat_depth_adjustable"] = True
        for search in connection.searches:
            search["filters"].update(deepcopy(mission["filters"]))
        connections[run_id] = connection
        run_ids[mission["canonical_query_id"]] = str(run_id)
    reads = []

    class Router:
        active = None

        def execute(self, sql, params=None):
            if "mosaic.agent_turn AS turn" in sql:
                reads.append(params[0])
                self.active = connections[params[0]]
            return self.active.execute(sql, params)

    @contextmanager
    def connect():
        yield Router()

    states = [
        SimpleNamespace(
            lab_id=i, source_state="solved", database_state="applied", detail="applied"
        )
        for i in (1, 2, 3)
    ]
    monkeypatch.setattr(receipt, "connect", connect)
    monkeypatch.setattr(receipt, "lab_states", lambda: SimpleNamespace(labs=states))
    monkeypatch.setattr(lab_proof, "resolve_evidence", _evidence_row)
    payload = {"version": 1, "identity": {"source_sha256": "current"}, "runs": run_ids}
    return payload, connections, reads, states


def test_replay_grades_both_real_persistence_paths_and_ignores_display_metadata(
    saved_runs,
):
    payload, connections, reads, _ = saved_runs
    checks = receipt.replay_receipt(payload, payload["identity"])
    assert len(checks) >= 30
    assert all(check.passed for check in checks), [
        (c.name, c.detail) for c in checks if not c.passed
    ]
    assert set(reads) == set(connections)
    for connection in connections.values():
        assert any("mosaic.agent_tool_event" in sql for sql in connection.statements)
        assert any("mosaic.search_result_event" in sql for sql in connection.statements)
        connection.turn["metadata"]["display_title"] = "A different browser title"
    assert all(c.passed for c in receipt.replay_receipt(payload, payload["identity"]))


def test_replay_rejects_evidence_changed_since_validation_and_recovers_byte_identical(
    saved_runs, monkeypatch
):
    payload, _, reads, _ = saved_runs
    baseline = deepcopy(_evidence_row(9001))
    changed = dict(baseline, revision="different")
    monkeypatch.setattr(
        lab_proof,
        "resolve_evidence",
        lambda eid: changed if eid == 9001 else _evidence_row(eid),
    )
    checks = receipt.replay_receipt(payload, payload["identity"])
    with pytest.raises(validate_lab.LabValidationError, match="resolve"):
        validate_lab._graded(checks)
    assert len(reads) == 2
    monkeypatch.setattr(lab_proof, "resolve_evidence", _evidence_row)
    assert _evidence_row(9001) == baseline
    assert all(c.passed for c in receipt.replay_receipt(payload, payload["identity"]))


def test_replay_refuses_changed_code_missing_control_and_rebroken_seam(saved_runs):
    payload, _, reads, states = saved_runs
    with pytest.raises(ValueError, match="different code or settings"):
        receipt.replay_receipt(payload, {"source_sha256": "changed"})
    assert not reads
    missing = deepcopy(payload)
    del missing["runs"]["G-019"]
    with pytest.raises(ValueError, match="run both"):
        receipt.replay_receipt(missing, payload["identity"])
    states[2].source_state = "broken"
    with pytest.raises(ValueError, match="repair and apply"):
        receipt.replay_receipt(payload, payload["identity"])
    assert not reads


def test_replay_will_not_accept_a_different_question(saved_runs):
    payload, connections, _, _ = saved_runs
    next(iter(connections.values())).turn["user_message"] = "A different request"
    with pytest.raises(ValueError, match="different G-021 run"):
        receipt.replay_receipt(payload, payload["identity"])


def test_source_binding_changes_with_agent_code_but_not_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(
        receipt, "compute_retrieval_fingerprint", lambda root: "retrieval"
    )
    for path in (
        "service/agent.py",
        "scripts/validate_lab.py",
        "scripts/lab_state.py",
        "uv.lock",
    ):
        target = tmp_path / path
        target.parent.mkdir(exist_ok=True)
        target.write_text("original")
    original = receipt.source_digest(tmp_path)
    (tmp_path / "README.md").write_text("New title")
    assert receipt.source_digest(tmp_path) == original
    agent = tmp_path / "service/agent.py"
    before = agent.read_bytes()
    agent.write_text("changed")
    assert receipt.source_digest(tmp_path) != original
    agent.write_bytes(before)
    assert receipt.source_digest(tmp_path) == original


def test_cli_reuse_never_invokes_the_agent(saved_runs, monkeypatch, tmp_path):
    import json

    payload, _, reads, _ = saved_runs
    path = tmp_path / "lab-3.json"
    path.write_text(json.dumps(payload))
    requests = []

    def request(base, route, body=None):
        requests.append(route)
        assert route == "/api/readiness"
        return {}

    monkeypatch.setattr(validate_lab, "_request", request)
    monkeypatch.setattr(receipt, "validation_identity", lambda *_: payload["identity"])
    checks = validate_lab.validate_lab_3("http://example.test", reuse_receipt=path)
    assert len(checks) >= 30
    assert requests == ["/api/readiness"]
    assert len(reads) == 2
