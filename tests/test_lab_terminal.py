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


def test_search_context_sets_the_applications_hnsw_settings_for_the_session():
    values = {key: "1" for key in lab_terminal.HNSW_SETTINGS.values()}
    sql = lab_terminal.sql_context(values)
    for setting, key in lab_terminal.HNSW_SETTINGS.items():
        assert f"set_config('{setting}', :'{key}', false)" in sql
    assert "set_config" not in lab_terminal.sql_context({"lab_query": "q"})


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
        "evidence_successes": 2,
        "evidence_errors": 0,
    }
    conn.execute.return_value.fetchall.return_value = [row]
    assert lab_terminal.failed_turn(conn, "question", "start", "end") == row


@pytest.mark.parametrize("successes,errors", [(0, 1), (0, 0), (1, 1)])
def test_evidence_environment_failure_is_not_the_lab_baseline(successes, errors):
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [
        {
            "agent_turn_id": "id",
            "extracted_intent": {"usage": {"error_type": "GroundingContractError"}},
            "evidence_successes": successes,
            "evidence_errors": errors,
        }
    ]
    with pytest.raises(LabValidationError, match="Evidence baseline rule"):
        lab_terminal.failed_turn(conn, "question", "start", "end")


def test_sql_context_uses_the_vector_saved_by_the_search_not_new_inference(
    monkeypatch, tmp_path
):
    from service.models import RetrievalProfile

    mission = lab_checks.load_mission("rank")
    vector = [0.125] * 1024
    ready = {
        "database": {
            "dataset_id": mission["dataset_id"],
            "product_count": 500000,
            "embedded_product_count": 500000,
            "catalog_ready": True,
        },
        "source": {"dataset_manifest_sha256": "hash"},
        "configured_models": {"embed": "model"},
    }
    event = {
        "run": {
            "search_event_id": "d28e43b7-6557-43bc-b589-11951ca5e5a7",
            "dataset_manifest_sha256": "hash",
            "normalized_query": mission["query"],
            "embedding_model_id": "model",
            "retrieval_profile": RetrievalProfile().model_dump(),
            "diagnostics": {"query_embedding": vector},
        },
        "candidates": [{"product_id": 1}],
    }
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
        "service.catalog_runtime.active_dataset", lambda: mission["dataset_id"]
    )
    monkeypatch.setattr(
        lab_terminal,
        "_request",
        lambda api, route: ready if route == "/api/readiness" else event,
    )
    monkeypatch.setattr(
        lab_terminal,
        "_search",
        lambda *args: {
            "search_event_id": "d28e43b7-6557-43bc-b589-11951ca5e5a7",
            "diagnostics": {"embedding_dimensions": 1024},
            "results": [],
        },
    )
    monkeypatch.setattr(
        "service.retrieval.RetrievalService._embedder",
        lambda self: pytest.fail("SQL context must not invoke embedding inference"),
    )
    lab_terminal.prepare(2, "before", "http://localhost", tmp_path)
    context = json.loads((tmp_path / "context.json").read_text())
    assert json.loads(context["lab_vector"]) == vector


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
            "catalog_ready": True,
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
    expected = "has not started" if drift == "missing_before" else "cannot be compared"
    with pytest.raises(LabValidationError, match=expected):
        lab_terminal.prepare(2, "after", "http://localhost", tmp_path)


def test_an_empty_search_is_not_a_broken_baseline():
    with pytest.raises(LabValidationError, match="returned no candidates") as refused:
        lab_terminal.require_broken_search(
            {"candidates": []}, {"target_product_ids": [2]}
        )
    assert not isinstance(refused.value, lab_terminal.AlreadyRepaired)


def test_a_search_that_already_finds_the_target_is_reported_as_repaired():
    with pytest.raises(lab_terminal.AlreadyRepaired, match="already finds product 2"):
        lab_terminal.require_broken_search(
            {"candidates": [{"product_id": 2}]}, {"target_product_ids": [2]}
        )


def test_real_missing_target_is_a_broken_baseline():
    lab_terminal.require_broken_search(
        {"candidates": [{"product_id": 1}]}, {"target_product_ids": [2]}
    )


def test_target_summary_names_the_missing_product_and_the_pool_size():
    mission = lab_checks.load_mission("retrieve")
    rows = [{"product_id": 1, "fused_rank": 1, "result_rank": 1}] * 50

    line = lab_terminal.target_summary({"candidates": rows}, mission)

    assert line == (
        f"Target {mission['target_product_ids'][0]} ({mission['target_display_name']}): "
        "not on the shortlist of 50, so reranking never saw it."
    )


@pytest.mark.parametrize("name", ["retrieve", "rank"])
def test_before_and_after_name_the_target_once_and_fit_a_laptop_terminal(name):
    mission = lab_checks.load_mission(name)
    target = {
        "product_id": mission["target_product_ids"][0],
        "fused_rank": 21,
        "result_rank": 5,
        "fts_rank": None,
        "fuzzy_rank": None,
        "semantic_rank": 10,
    }

    lines = lab_terminal.before_after_lines({"candidates": [target]}, mission)

    assert lines == [
        f"Target {target['product_id']} ({mission['target_display_name']})",
        "Before: not on the shortlist.",
        "After:  combined position 21, final position 5; found by semantic search rank 10.",
    ]
    missing = lab_terminal.target_summary(
        {"candidates": [{"product_id": 1}] * 50}, mission
    )
    assert max(len(line) for line in [*lines, missing]) <= 95


def test_target_summary_names_positions_and_only_the_methods_that_found_it():
    mission = lab_checks.load_mission("retrieve")
    target = {
        "product_id": mission["target_product_ids"][0],
        "fused_rank": 2,
        "result_rank": 1,
        "fts_rank": None,
        "fuzzy_rank": 1,
        "semantic_rank": None,
    }

    line = lab_terminal.target_summary({"candidates": [target]}, mission)

    assert "combined position 2, final position 1" in line
    assert "found by fuzzy matching rank 1." in line
    assert "words" not in line and "meaning" not in line


def test_a_run_saves_under_the_checkout_and_honours_lab_api_url(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAB_API_URL", "http://api.internal:9000")
    calls = []
    monkeypatch.setattr(lab_terminal, "prepare", lambda *args: calls.append(args))
    monkeypatch.setattr(
        "sys.argv", ["lab_terminal.py", "run", "--lab", "2", "--phase", "after"]
    )

    assert lab_terminal.main() == 0

    [(lab, phase, api_url, output)] = calls
    assert (lab, phase, api_url) == (2, "after", "http://api.internal:9000")
    assert output == lab_terminal.ROOT / ".local/lab-2"
