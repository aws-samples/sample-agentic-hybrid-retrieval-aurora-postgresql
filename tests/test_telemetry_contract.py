"""Portable telemetry must preserve Mosaic truth without exporting catalog data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from service.config import get_settings
from service.models import RetrievalDiagnostics, RetrievalProfile, SearchResponse
from service.synthesis import _combined_usage
from service.telemetry import (
    TraceCorrelation,
    agent_outcome_attributes,
    correlation_from_span_context,
    observe_agent_turn,
    persist_retrieval_telemetry,
    record_retrieval_span,
    retrieval_span_attributes,
)
from service.telemetry_contract import build_agent_telemetry_contract

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_agentcore_observability_is_disabled_and_content_safe_by_default(
    monkeypatch,
):
    monkeypatch.delenv("MOSAIC_AGENTCORE_OBSERVABILITY", raising=False)
    monkeypatch.delenv("MOSAIC_AGENTCORE_CAPTURE_CONTENT", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.agentcore_observability_enabled is False
    assert settings.agentcore_capture_content is False


def test_agentcore_observability_requires_an_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("MOSAIC_AGENTCORE_OBSERVABILITY", "true")
    monkeypatch.setenv("MOSAIC_AGENTCORE_CAPTURE_CONTENT", "true")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.agentcore_observability_enabled is True
    assert settings.agentcore_capture_content is True


def test_retrieval_export_contains_aggregates_but_no_candidate_identity():
    search_event_id = uuid4()
    attributes = retrieval_span_attributes(
        search_event_id=search_event_id,
        candidate_counts={
            "fused_pool": 50,
            "fts_in_pool": 12,
            "trigram_in_pool": 4,
            "semantic_in_pool": 48,
        },
        result_limit=12,
        authorized_limit=4,
        stage_timings_ms={
            "embedding": 18.2,
            "postgresql_retrieval": 31.4,
            "rerank": 44.8,
        },
        total_latency_ms=98,
        rerank_status="applied",
        retrieval_fingerprint="a" * 64,
        source_revision="b" * 40,
        dataset_manifest_sha256="c" * 64,
        status="completed",
    )

    encoded = json.dumps(attributes, sort_keys=True)
    assert attributes["gen_ai.operation.name"] == "execute_tool"
    assert attributes["gen_ai.tool.name"] == "search_products"
    assert attributes["mosaic.search_event.id"] == str(search_event_id)
    assert attributes["mosaic.candidates.fused_pool"] == 50
    assert attributes["mosaic.candidates.served_limit"] == 12
    assert attributes["mosaic.candidates.authorized_limit"] == 4
    assert "product_id" not in encoded
    assert "sku" not in encoded
    assert "title" not in encoded
    assert "query" not in encoded


def test_agent_export_summarizes_grounding_without_product_identity():
    attributes = agent_outcome_attributes(
        {
            "trace": [
                {"tool": "get_product_evidence", "outcome": "success"},
                {"tool": "get_product_evidence", "outcome": "denied"},
            ],
            "evidence_by_product": {101: [9001]},
            "answer_of_record": {
                "recommendations": [{"product_id": 101}],
                "citations": [{"product_id": 101, "evidence_id": 9001}],
            },
        }
    )

    encoded = json.dumps(attributes, sort_keys=True)
    assert attributes["mosaic.grounding.products_with_evidence"] == 1
    assert attributes["mosaic.grounding.citation_validation"] == "passed"
    assert attributes["mosaic.authorization.denied_count"] == 1
    assert "101" not in encoded
    assert "9001" not in encoded


def test_search_event_id_is_correlation_data_not_an_otel_trace_id():
    search_event_id = uuid4()
    correlation = correlation_from_span_context(
        trace_id=int("12" * 16, 16),
        span_id=int("34" * 8, 16),
        is_valid=True,
    )

    assert correlation.trace_id == "12" * 16
    assert correlation.span_id == "34" * 8
    assert str(search_event_id).replace("-", "") != correlation.trace_id


def test_broken_otel_provider_degrades_to_noop_without_breaking_mosaic(
    monkeypatch,
):
    monkeypatch.setenv("MOSAIC_AGENTCORE_OBSERVABILITY", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "service.telemetry.trace.get_tracer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("exporter")),
    )

    correlation = record_retrieval_span(
        search_event_id=uuid4(),
        query="quiet keyboard",
        candidate_counts={"fused_pool": 50},
        result_limit=12,
        authorized_limit=2,
        stage_timings_ms={"postgresql_retrieval": 30.0},
        total_latency_ms=80,
        rerank_status="applied",
        retrieval_fingerprint="a" * 64,
        source_revision="b" * 40,
        dataset_manifest_sha256="c" * 64,
        status="completed",
        start_time_ns=1,
    )
    state = {
        "agent_session_id": uuid4(),
        "agent_turn_id": uuid4(),
    }
    executed = False
    with observe_agent_turn(state, "Find a quiet keyboard.") as observation:
        executed = True
        assert observation.span is None

    assert correlation == TraceCorrelation()
    assert executed is True


def test_search_correlation_is_appended_to_the_existing_diagnostics_receipt(
    monkeypatch,
):
    captured: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, parameters):
            captured["sql"] = sql
            captured["parameters"] = parameters

        def commit(self):
            captured["committed"] = True

    monkeypatch.setattr("service.telemetry.connect", lambda: Connection())
    monkeypatch.setattr(
        "service.telemetry._current_retrieval_fingerprint",
        lambda: "a" * 64,
    )
    monkeypatch.setattr(
        "service.telemetry.record_retrieval_span",
        lambda **_kwargs: TraceCorrelation(
            trace_id="12" * 16,
            span_id="34" * 8,
        ),
    )
    response = SearchResponse(
        search_event_id=uuid4(),
        query="quiet keyboard",
        normalized_query="quiet keyboard",
        applied_filters={},
        results=[],
        diagnostics=RetrievalDiagnostics(
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            embedding_model_id="embed-model",
            embedding_dimensions=1024,
            rerank_model_id="rerank-model",
            rerank_status="applied",
            retrieval_profile=RetrievalProfile(
                result_limit=12,
                authorized_limit=2,
            ),
            candidate_counts={"fused_pool": 50},
            stage_timings_ms={"postgresql_retrieval": 30.0},
            total_latency_ms=80,
        ),
    )

    persist_retrieval_telemetry(
        response=response,
        query=response.query,
        start_time_ns=1,
    )

    assert "'{telemetry}'" in str(captured["sql"])
    payload = json.loads(captured["parameters"][0])
    assert payload == {
        "trace_id": "12" * 16,
        "span_id": "34" * 8,
        "retrieval_fingerprint": "a" * 64,
    }
    assert captured["parameters"][1] == response.search_event_id
    assert captured["committed"] is True


def test_timeline_maps_retrieve_rank_reason_without_losing_exact_rrf_receipts():
    agent_turn_id = uuid4()
    agent_session_id = uuid4()
    search_event_id = uuid4()
    occurred_at = datetime(2026, 9, 2, 14, 30, tzinfo=UTC)
    contract = build_agent_telemetry_contract(
        turn={
            "agent_turn_id": agent_turn_id,
            "agent_session_id": agent_session_id,
            "user_message": "Find a quiet keyboard.",
            "assistant_message": "Choose the cited option [1].",
            "extracted_intent": {
                "telemetry": {
                    "completed_at": occurred_at.isoformat(),
                    "duration_ms": 650,
                    "status": "completed",
                    "trace_id": "12" * 16,
                    "span_id": "34" * 8,
                },
                "usage": {
                    "strands": {
                        "input_tokens": 120,
                        "output_tokens": 40,
                        "total_tokens": 160,
                    },
                    "synthesis": {
                        "inputTokens": 80,
                        "outputTokens": 20,
                        "totalTokens": 100,
                        "stopReason": "end_turn",
                        "latencyMs": 420,
                    },
                },
                "selected_products": [{"product_id": 101}],
            },
            "created_at": occurred_at,
        },
        session={
            "metadata": {
                "agent_model_id": "planner-model",
                "synthesis_model_id": "synthesis-model",
            }
        },
        searches=[
            {
                "search_event_id": search_event_id,
                "occurred_at": occurred_at,
                "retrieval_profile": {
                    "result_limit": 2,
                    "authorized_limit": 1,
                },
                "source_revision": "d" * 40,
                "dataset_manifest_sha256": "e" * 64,
                "retrieval_fingerprint": "f" * 64,
                "candidate_counts": {"fused_pool": 3},
                "total_latency_ms": 90,
                "diagnostics": {
                    "status": "ok",
                    "rerank_status": "applied",
                    "telemetry": {
                        "trace_id": "56" * 16,
                        "span_id": "78" * 8,
                        "retrieval_fingerprint": "f" * 64,
                    },
                    "stage_timings_ms": {
                        "embedding": 10,
                        "postgresql_retrieval": 30,
                        "rerank": 40,
                    },
                },
            }
        ],
        candidates=[
            {
                "search_event_id": search_event_id,
                "product_id": 101,
                "result_rank": 1,
                "fused_rank": 3,
                "rerank_rank": 1,
                "scores": {"rrf": 0.04},
                "provenance": {
                    "channels": {
                        "fts": {"rrf_contribution": 0.01},
                        "trigram": {"rrf_contribution": 0.02},
                        "vector": {"rrf_contribution": 0.01},
                    }
                },
            },
            {
                "search_event_id": search_event_id,
                "product_id": 102,
                "result_rank": 2,
                "fused_rank": 1,
                "rerank_rank": 2,
                "scores": {"rrf": 0.03},
                "provenance": {"channels": {}},
            },
            {
                "search_event_id": search_event_id,
                "product_id": 103,
                "result_rank": 3,
                "fused_rank": 2,
                "rerank_rank": 3,
                "scores": {"rrf": 0.02},
                "provenance": {"channels": {}},
            },
        ],
        tools=[
            {
                "tool_name": "get_product_evidence",
                "outcome": "success",
                "duration_ms": 12,
                "input_payload": {"product_id": 101},
                "output_payload": {"result_count": 2},
            },
            {
                "tool_name": "synthesize_cited_answer",
                "outcome": "success",
                "duration_ms": 420,
                "input_payload": {"product_ids": [101]},
                "output_payload": {"citations": [{"number": 1}]},
            },
        ],
    )

    assert [stage.id for stage in contract.stages] == [
        "retrieve",
        "rank",
        "reason",
    ]
    receipt = contract.stages[1].details["receipts"][0]
    assert receipt["rrf_contributions"] == {
        "fts": 0.01,
        "trigram": 0.02,
        "semantic": 0.01,
    }
    assert receipt["rerank_movement"] == -2
    assert receipt["disposition"] == "authorized"
    assert contract.stages[1].details["receipts"][1]["disposition"] == (
        "served_not_authorized"
    )
    assert contract.stages[1].details["receipts"][2]["drop_reason"] == (
        "outside_served_window"
    )
    assert contract.stages[2].details["evidence_coverage"] == {
        "selected_products": 1,
        "products_with_evidence": 1,
        "complete": True,
    }
    assert contract.stages[2].details["citation_validation"] == {
        "status": "passed",
        "citation_count": 1,
    }
    assert contract.model.stop_reason == "end_turn"
    assert contract.model.latency_ms == 420


def test_correlation_uses_existing_json_receipts_not_a_bootstrap_schema_change():
    agent_source = (ROOT / "service" / "agent_tools.py").read_text()
    telemetry_source = (ROOT / "service" / "telemetry.py").read_text()
    agent_sql = (ROOT / "db" / "sql" / "10_agent_audit.sql").read_text()
    retrieval_sql = (ROOT / "db" / "sql" / "12_telemetry.sql").read_text()

    assert '"telemetry": state.get("telemetry", {})' in agent_source
    assert "'{telemetry}'" in telemetry_source
    assert "retrieval_fingerprint" in telemetry_source
    for column in ("trace_id", "span_id", "retrieval_fingerprint"):
        assert column not in retrieval_sql
    agent_turn_sql = agent_sql.split(
        "CREATE TABLE IF NOT EXISTS mosaic.agent_turn",
        1,
    )[1].split("CREATE TABLE IF NOT EXISTS mosaic.agent_tool_event", 1)[0]
    for column in ("trace_id", "span_id", "completed_at", "duration_ms"):
        assert column not in agent_turn_sql


def test_workshop_bootstrap_keeps_the_agentcore_exporter_out_of_the_base_install():
    bootstrap = (ROOT / "deploy" / "mosaic-bootstrap.sh").read_text()
    project = (ROOT / "pyproject.toml").read_text()

    assert "uv sync --frozen" in bootstrap
    assert "agentcore-observability" not in bootstrap
    assert "agentcore-observability" in project
    assert "aws-opentelemetry-distro" in project


def test_api_declares_the_turn_telemetry_route():
    from service.main import app

    declared = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/telemetry/agent-turns/{agent_turn_id}" in declared


def test_synthesis_usage_preserves_bedrock_latency():
    usage = _combined_usage(
        [
            {
                "usage": {
                    "inputTokens": 20,
                    "outputTokens": 5,
                    "totalTokens": 25,
                },
                "metrics": {"latencyMs": 180},
                "stopReason": "end_turn",
            },
            {
                "usage": {
                    "inputTokens": 30,
                    "outputTokens": 8,
                    "totalTokens": 38,
                },
                "metrics": {"latencyMs": 220},
                "stopReason": "end_turn",
            },
        ]
    )

    assert usage["latencyMs"] == 400
    assert usage["stopReason"] == "end_turn"


def _declined_turn(outcome: str | None) -> dict[str, object]:
    """A persisted turn whose synthesis receipt is a refusal, not a failure."""
    return {
        "agent_turn_id": uuid4(),
        "agent_session_id": uuid4(),
        "user_message": "replacement charging brick for model A2342",
        "assistant_message": "Nothing in the catalog matches the term 'A2342'.",
        "extracted_intent": {
            "telemetry": {"status": "completed"},
            "selected_products": [],
            "outcome": outcome,
            "decline_reason": "unanchored_query_terms: 'A2342'",
        },
        "created_at": datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
    }


_DECLINED_SYNTHESIS_TOOLS = [
    {
        "tool_name": "synthesize_cited_answer",
        "outcome": "denied",
        "duration_ms": 3,
        "input_payload": {"product_ids": [101]},
        "output_payload": {"citations": []},
    }
]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("declined", "declined"), (None, "failed")],
    ids=["declined", "no-outcome"],
)
def test_a_declined_turn_reports_its_own_citation_status(outcome, expected):
    """A refusal is not a citation failure, and the timeline must separate them.

    Both parameters send the identical `denied` synthesis receipt with zero
    citations. Only the persisted outcome differs, so the assertion cannot pass
    by reading the tool row, which is what produced the wrong `failed` before.
    """
    contract = build_agent_telemetry_contract(
        turn=_declined_turn(outcome),
        session={"metadata": {}},
        searches=[],
        candidates=[],
        tools=_DECLINED_SYNTHESIS_TOOLS,
    )

    assert contract.stages[2].details["citation_validation"] == {
        "status": expected,
        "citation_count": 0,
    }


def test_a_declined_run_is_not_counted_as_an_authorization_denial():
    """`denied` is the right tool outcome and the wrong denial-metric input.

    Nothing was withheld from the model on a decline; the catalog does not carry
    what the request named. Counting it would make the denial rate track absent
    search terms instead of scope violations.
    """
    trace = [
        {"tool": "search_products", "outcome": "success"},
        {"tool": "synthesize_cited_answer", "outcome": "denied"},
    ]

    declined = agent_outcome_attributes(
        {
            "trace": trace,
            "evidence_by_product": {},
            "answer_of_record": {
                "recommendations": [],
                "citations": [],
                "outcome": "declined",
            },
        }
    )
    grounded = agent_outcome_attributes(
        {
            "trace": trace,
            "evidence_by_product": {},
            "answer_of_record": {
                "recommendations": [{"product_id": 101}],
                "citations": [{"product_id": 101}],
                "outcome": "grounded",
            },
        }
    )

    assert declined["mosaic.authorization.denied_count"] == 0
    assert grounded["mosaic.authorization.denied_count"] == 1, (
        "the same denied step stopped counting on a grounded run, so the "
        "exemption is no longer scoped to a decline"
    )
    assert declined["mosaic.tools.count"] == 2


def test_a_declined_run_still_counts_a_real_authorization_denial():
    """The exemption covers the decline's own receipt, not every denial.

    A scope violation on another tool is a genuine denial and must survive.
    """
    attributes = agent_outcome_attributes(
        {
            "trace": [
                {"tool": "get_product_evidence", "outcome": "denied"},
                {"tool": "synthesize_cited_answer", "outcome": "denied"},
            ],
            "evidence_by_product": {},
            "answer_of_record": {
                "recommendations": [],
                "citations": [],
                "outcome": "declined",
            },
        }
    )

    assert attributes["mosaic.authorization.denied_count"] == 1
