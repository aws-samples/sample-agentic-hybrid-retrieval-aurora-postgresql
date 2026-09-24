"""Saved completion checks must retain the order of failed and repaired drafts."""

import json
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_agent_coverage_decline import _FakeConnection, grounded, product, run_state
from test_lab_proof import _citation, _grounded_connection

from service import agent_tools, lab_proof
from service.models import AgentCitation
from service.telemetry_contract import load_agent_turn_rows


def test_saved_retry_keeps_order_and_citations_on_success_only(monkeypatch):
    state = run_state(coverage=[grounded()])
    state["trace"] = [
        {
            "tool": "synthesize_cited_answer",
            "detail": "Draft rejected",
            "outcome": "error",
        },
        {
            "tool": "synthesize_cited_answer",
            "detail": "Draft accepted",
            "outcome": "success",
        },
    ]
    citation = AgentCitation(**_citation(1, 9101))
    state["answer_of_record"] = {
        "answer": "Supported answer [1].",
        "citations": [citation],
        "recommendations": [product()],
        "usage": {},
    }
    connection = _FakeConnection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(agent_tools, "connect", connect)
    agent_tools.persist_completed_run(state, usage={})
    assert connection.committed and len(connection.tool_rows) == 1
    rows = connection.tool_rows[0]
    assert len(rows) == 2
    payloads = [json.loads(row["output_payload"]) for row in rows]
    assert payloads[0]["citations"] is None
    assert [payload.get("sequence") for payload in payloads] == [1, 2]
    assert payloads[1]["citations"] == [citation.model_dump()]


def _ordered_connection():
    connection = _grounded_connection()
    for sequence, tool in enumerate(connection.tools, 1):
        tool["output_payload"] = dict(tool["output_payload"])
        tool["output_payload"]["sequence"] = sequence
    success = connection.tools[-1]
    assert success["tool_name"] == "synthesize_cited_answer"
    failure = deepcopy(success)
    failure["outcome"] = "error"
    failure["output_payload"]["citations"] = None
    success["output_payload"]["sequence"] += 1
    connection.tools.append(failure)
    return connection


def test_loader_restores_call_order_before_completion_proof():
    connection = _ordered_connection()
    original_order = deepcopy(connection.tools)
    rows = load_agent_turn_rows(connection, connection.turn["agent_turn_id"])
    assert rows is not None
    assert len(rows.tools) == len(original_order) > 2
    assert lab_proof._synthesis_event(rows.tools)["outcome"] == "success"
    assert connection.tools == original_order
    assert any("mosaic.agent_tool_event" in sql for sql in connection.statements)
    connection.tools.reverse()
    rows_reversed = load_agent_turn_rows(connection, connection.turn["agent_turn_id"])
    assert rows_reversed.tools == rows.tools
    connection.tools[-1]["output_payload"]["detail"] = "Different display wording"
    assert (
        lab_proof._synthesis_event(
            load_agent_turn_rows(connection, connection.turn["agent_turn_id"]).tools
        )["outcome"]
        == "success"
    )


@pytest.mark.parametrize("bad_sequence", [None, 0, 99, "2", True, 1])
def test_loader_rejects_incomplete_or_invalid_sequence(bad_sequence):
    connection = _ordered_connection()
    connection.tools[-1]["output_payload"]["sequence"] = bad_sequence
    with pytest.raises(ValueError, match="tool sequence.*rerun"):
        load_agent_turn_rows(connection, connection.turn["agent_turn_id"])


def test_legacy_single_synthesis_runs_keep_their_existing_read_order():
    connection = _grounded_connection()
    rows = load_agent_turn_rows(connection, connection.turn["agent_turn_id"])
    assert rows is not None and rows.tools == connection.tools
