"""Reject misleading run identities and executable context values."""

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from scripts import lab_terminal
from scripts.validate_lab import LabValidationError
from service import lab_checks


@pytest.mark.parametrize("stage", ["retrieve", "rank", "reason"])
def test_request_comes_from_the_mission(stage):
    mission = lab_checks.load_mission(stage)
    payload = lab_terminal.request_payload(mission)
    question, limit = (
        ("question", "result_limit") if stage == "reason" else ("query", "limit")
    )
    assert payload[question] == mission["query"]
    assert payload["filters"] == mission["filters"]
    assert payload[limit] == mission["top_k"]
    if stage != "reason":
        assert payload["rerank"] is payload["include_diagnostics"] is True


def test_untrusted_values_cannot_become_psql_commands():
    dangerous = "a'\n\\! touch /tmp/should-not-exist\n`id` $(id)"
    sql = lab_terminal.sql_context({"lab_query": dangerous})
    assert dangerous not in sql
    assert "\\!" not in sql
    assert dangerous.encode().hex() in sql


@pytest.mark.parametrize(
    "key", ["", "lab_x;drop", "lab_1", "lab_é", "other", "lab_x\n\\!"]
)
def test_invalid_context_names_fail(key):
    with pytest.raises(LabValidationError, match="Context name rule"):
        lab_terminal.sql_context({key: "value"})


def test_catalog_and_both_event_identities_are_checked():
    sql = lab_terminal.sql_context({"lab_search_id": "a", "lab_before_id": "b"})
    assert "catalog_sha256" in sql
    assert "search_event_id = :'lab_search_id'::uuid" in sql
    assert "search_event_id = :'lab_before_id'::uuid" in sql
    assert sql.count("RAISE EXCEPTION") == 3


@pytest.mark.parametrize("count", [0, 2])
def test_failed_http_call_must_match_exactly_one_turn(count):
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [{}] * count
    with pytest.raises(LabValidationError, match="Failed-turn identity rule"):
        lab_terminal.failed_turn(conn, "question", "start", "end")
    assert conn.execute.call_args.args[1] == ("question", "start", "end")


@pytest.mark.parametrize("error", ["RuntimeError", None])
def test_generic_runtime_failure_is_not_lab_proof(error):
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [
        {"extracted_intent": {"usage": {"error_type": error}}}
    ]
    with pytest.raises(LabValidationError, match="not the lab"):
        lab_terminal.failed_turn(conn, "question", "start", "end")


def test_actual_grounding_failure_is_inspectable():
    conn = Mock()
    row = {
        "agent_turn_id": "id",
        "extracted_intent": {"usage": {"error_type": "GroundingContractError"}},
    }
    conn.execute.return_value.fetchall.return_value = [row]
    assert lab_terminal.failed_turn(conn, "question", "start", "end") == row


@pytest.mark.parametrize(
    "drift", ["missing_before", "request", "catalog_hash", "models"]
)
def test_pair_drift_stops_before_another_paid_request(monkeypatch, tmp_path, drift):
    mission = lab_checks.load_mission("rank")
    monkeypatch.setattr(
        "service.catalog_runtime.active_dataset", lambda: mission["dataset_id"]
    )
    ready = {
        "database": {
            "dataset_id": mission["dataset_id"],
            "product_count": 500000,
            "embedded_product_count": 500000,
        },
        "source": {"dataset_manifest_sha256": "hash"},
        "configured_models": {"embed": "model"},
    }
    monkeypatch.setattr(lab_terminal, "_request", lambda *args: ready)
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {
        "dataset_id": mission["dataset_id"],
        "catalog_sha256": "hash",
    }

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr("service.db.connect", connect)
    monkeypatch.setattr(
        lab_terminal,
        "_search",
        lambda *args: pytest.fail("Search must not run after pair drift"),
    )
    before = {
        "request": lab_terminal.request_payload(mission),
        "catalog_hash": "hash",
        "models": ready["configured_models"],
    }
    if drift != "missing_before":
        before[drift] = "changed"
        (tmp_path / "before-state.json").write_text(json.dumps(before))
    with pytest.raises(LabValidationError, match="Pair rule"):
        lab_terminal.prepare(2, "after", "http://localhost", tmp_path)


@pytest.mark.parametrize("rows", [[], [{"product_id": 2}]])
def test_empty_or_repaired_search_is_not_a_broken_baseline(rows):
    with pytest.raises(LabValidationError, match="Before-state rule"):
        lab_terminal.require_broken_search(
            {"candidates": rows}, {"target_product_ids": [2]}
        )


def test_real_missing_target_is_a_broken_baseline():
    lab_terminal.require_broken_search(
        {"candidates": [{"product_id": 1}]}, {"target_product_ids": [2]}
    )
