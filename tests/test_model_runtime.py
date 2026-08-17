import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from service import agent_tools
from service.agent import (
    GroundingContractError,
    ProductDiscoveryAgent,
    _agent_prompt,
    build_agent,
)
from service.catalog import _detail
from service.config import get_settings
from service.embeddings import BedrockEmbeddingProvider, _cohere_request
from service.main import app
from service.model_runtime import ModelRuntimeError
from service.models import (
    AgentCitation,
    AgentRequest,
    AgentResponse,
    EvidenceRecord,
    ProductSummary,
    SearchFilters,
    SearchResponse,
    SourceAttribution,
)
from service.rerank import BedrockReranker
from service.synthesis import synthesize_cited_answer

ROOT = Path(__file__).resolve().parents[1]


class FakeEmbeddingClient:
    def __init__(self, dimensions: int):
        self.dimensions = dimensions
        self.requests: list[dict] = []

    def invoke_model(self, **kwargs):
        self.requests.append(kwargs)
        payload = json.loads(kwargs["body"])
        vectors = [
            [float(index + 1)] * self.dimensions
            for index, _ in enumerate(payload["texts"])
        ]
        return {
            "body": io.BytesIO(json.dumps({"embeddings": {"float": vectors}}).encode())
        }


class FakeRerankClient:
    def __init__(self):
        self.request = None

    def rerank(self, **kwargs):
        self.request = kwargs
        return {
            "results": [
                {"index": 1, "relevanceScore": 0.91},
                {"index": 0, "relevanceScore": 0.62},
            ]
        }


class FakeSynthesisClient:
    def __init__(
        self,
        answer: str | list[str],
        *,
        stop_reason: str | list[str] = "end_turn",
    ):
        self.answers = answer if isinstance(answer, list) else [answer]
        self.stop_reasons = (
            stop_reason if isinstance(stop_reason, list) else [stop_reason]
        )
        self.request = None
        self.requests: list[dict] = []

    def converse(self, **kwargs):
        self.request = kwargs
        self.requests.append(kwargs)
        index = min(len(self.requests) - 1, len(self.answers) - 1)
        stop_index = min(
            len(self.requests) - 1,
            len(self.stop_reasons) - 1,
        )
        return {
            "output": {
                "message": {
                    "content": [{"text": self.answers[index]}],
                }
            },
            "usage": {
                "inputTokens": 200,
                "outputTokens": 60,
                "totalTokens": 260,
            },
            "stopReason": self.stop_reasons[stop_index],
        }


def product() -> ProductSummary:
    return ProductSummary(
        product_id=101,
        sku="CE-AUDIO-0000101",
        title="AuriLogic Flight ANC",
        short_description="Quiet over-ear headphones with 48-hour battery life.",
        domain="consumer_electronics",
        category_key="over-ear-headphones",
        category_path="Audio > Over-Ear Headphones",
        brand="AuriLogic",
        model="FL-48",
        price_cents=17_999,
        list_price_cents=19_999,
        rating=4.7,
        review_count=842,
        availability="in_stock",
        inventory_count=31,
        attributes={
            "active_noise_cancellation": True,
            "battery_hours": 48,
        },
        tags=["travel", "noise cancellation"],
        sources=[
            SourceAttribution(
                source_uri="mosaic://product/101",
                revision="2026-08-07T12:00:00+00:00",
                title="AuriLogic Flight ANC",
                quote=("Quiet over-ear headphones with 48-hour battery life."),
            )
        ],
    )


def evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=9001,
        product_id=101,
        evidence_type="product_spec",
        source_name="Mosaic catalog specification",
        source_uri="mosaic://evidence/product-spec/101",
        revision="2026-08-07",
        title="AuriLogic Flight ANC specifications",
        text="48-hour battery life and active noise cancellation.",
        is_verified=True,
    )


def citation() -> AgentCitation:
    return AgentCitation(
        number=1,
        evidence_id=9001,
        evidence_type="product_spec",
        product_id=101,
        source_uri="mosaic://evidence/product-spec/101",
        revision="2026-08-07",
        title="AuriLogic Flight ANC specifications",
        quote="48-hour battery life and active noise cancellation.",
    )


def test_product_detail_replaces_the_inherited_group_field_once():
    detail = _detail(
        product(),
        {
            "long_description": "Complete product detail.",
            "canonical_group_id": "group-101",
            "source_system": "mosaic",
            "updated_at": datetime.now(UTC),
        },
        [],
        [],
    )

    assert detail.canonical_group_id == "group-101"
    assert detail.long_description == "Complete product detail."


def test_cohere_embed_v4_request_and_response(monkeypatch):
    settings = replace(
        get_settings(),
        embedding_model_id="us.cohere.embed-v4:0",
        vector_dimension=1024,
    )
    client = FakeEmbeddingClient(1024)
    monkeypatch.setattr(
        "service.embeddings.get_bedrock_client",
        lambda *_args, **_kwargs: client,
    )
    provider = BedrockEmbeddingProvider(settings)

    vectors = provider.embed_documents(["first product", "second product"])

    assert provider.model_id == "us.cohere.embed-v4:0"
    assert [len(vector) for vector in vectors] == [1024, 1024]
    request = json.loads(client.requests[0]["body"])
    assert request == _cohere_request(
        ["first product", "second product"],
        1024,
        "search_document",
    )


def test_embedding_dimension_mismatch_fails_closed(monkeypatch):
    settings = replace(get_settings(), vector_dimension=1024)
    client = FakeEmbeddingClient(512)
    monkeypatch.setattr(
        "service.embeddings.get_bedrock_client",
        lambda *_args, **_kwargs: client,
    )
    provider = BedrockEmbeddingProvider(settings)

    with pytest.raises(ValueError, match="returned 512 dimensions"):
        provider.embed_query("quiet headphones")


def test_cohere_rerank_preserves_source_indices(monkeypatch):
    client = FakeRerankClient()
    monkeypatch.setattr(
        "service.rerank.get_bedrock_client",
        lambda *_args, **_kwargs: client,
    )
    reranker = BedrockReranker(get_settings())

    results = reranker.rerank(
        "quiet travel headphones",
        ["first candidate", "second candidate"],
        2,
    )

    assert results == [(1, 0.91), (0, 0.62)]
    assert (
        client.request["rerankingConfiguration"]["bedrockRerankingConfiguration"][
            "numberOfResults"
        ]
        == 2
    )


def test_synthesis_returns_only_validated_citations():
    client = FakeSynthesisClient(
        "Summary\nChoose AuriLogic Flight ANC for long flights [1]."
    )

    answer, citations, usage = synthesize_cited_answer(
        "What should I use on a long flight?",
        [product()],
        [evidence()],
        client=client,
    )

    assert "[1]" in answer
    assert citations[0].evidence_id == 9001
    assert citations[0].source_uri == "mosaic://evidence/product-spec/101"
    assert usage["totalTokens"] == 260
    assert client.request["inferenceConfig"] == {"maxTokens": 1_400}
    assert (
        '"allowed_evidence_numbers": [1]'
        in client.request["messages"][0]["content"][0]["text"]
    )
    system_prompt = client.request["system"][0]["text"]
    assert "natural, confident shopping prose" in system_prompt
    assert '"Summary" or "Recommendations"' in system_prompt
    assert "standalone model code" in system_prompt
    assert 'heading "The deciding trade-off"' in system_prompt
    assert usage["stopReason"] == "end_turn"
    assert usage["attempts"] == 1


def test_synthesis_repairs_one_invalid_citation_draft_inside_its_boundary():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-40",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
        }
    )
    client = FakeSynthesisClient(
        [
            (
                "Summary\nAuriLogic Flight ANC and AuriLogic Office ANC are "
                "the options [1]."
            ),
            (
                "Summary\nThe two options fit different settings [1][2].\n"
                "Recommendations\n"
                "- AuriLogic Flight ANC is the travel choice [1].\n"
                "- AuriLogic Office ANC is the office choice [2].\n"
                "Trade-offs\nChoose by environment [1][2]."
            ),
        ]
    )

    answer, citations, usage = synthesize_cited_answer(
        "Compare the options.",
        [product(), second_product],
        [evidence(), second_evidence],
        client=client,
    )

    assert "Office ANC is the office choice [2]" in answer
    assert {citation.product_id for citation in citations} == {101, 102}
    assert len(client.requests) == 2
    assert usage["attempts"] == 2
    assert usage["totalTokens"] == 520


def test_synthesis_rejects_a_truncated_model_response():
    client = FakeSynthesisClient(
        "Choose AuriLogic Flight ANC for long flights [1].",
        stop_reason="max_tokens",
    )

    with pytest.raises(ValueError, match="max_tokens"):
        synthesize_cited_answer(
            "What should I use on a long flight?",
            [product()],
            [evidence()],
            client=client,
        )
    assert len(client.requests) == 2


def test_synthesis_rejects_citation_outside_retrieved_set():
    client = FakeSynthesisClient("Choose the product [2].")

    with pytest.raises(ValueError, match="outside the retrieved set"):
        synthesize_cited_answer(
            "What should I buy?",
            [product()],
            [evidence()],
            client=client,
        )


def test_synthesis_rejects_zero_as_an_evidence_number():
    client = FakeSynthesisClient("Choose AuriLogic Flight ANC [0].")

    with pytest.raises(ValueError, match="outside the retrieved set"):
        synthesize_cited_answer(
            "What should I buy?",
            [product()],
            [evidence()],
            client=client,
        )


def test_synthesis_requires_citations_for_every_selected_product():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-40",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
        }
    )
    client = FakeSynthesisClient(
        "Choose AuriLogic Flight ANC for travel [1]. "
        "AuriLogic Office ANC is the alternative [1]."
    )

    with pytest.raises(ValueError, match="did not cite every selected product"):
        synthesize_cited_answer(
            "Compare the options.",
            [product(), second_product],
            [evidence(), second_evidence],
            client=client,
        )


def test_synthesis_rejects_a_named_product_claim_citing_another_product():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-40",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
        }
    )
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC is the travel choice [2]. "
        "AuriLogic Office ANC is the office choice [1][2]."
    )

    with pytest.raises(ValueError, match="naming product 101"):
        synthesize_cited_answer(
            "Compare the options.",
            [product(), second_product],
            [evidence(), second_evidence],
            client=client,
        )


def test_synthesis_rejects_a_numeric_claim_absent_from_its_cited_evidence():
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC provides 60-hour battery life [1]."
    )

    with pytest.raises(ValueError, match="unsupported numeric claim.*60"):
        synthesize_cited_answer(
            "What should I use on a long flight?",
            [product()],
            [evidence()],
            client=client,
        )


def test_synthesis_does_not_accept_a_numeric_substring_as_support():
    source = evidence().model_copy(
        update={"text": "160-hour battery life and active noise cancellation."}
    )
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC provides 60-hour battery life [1]."
    )

    with pytest.raises(ValueError, match="unsupported numeric claim.*60"):
        synthesize_cited_answer(
            "What should I use on a long flight?",
            [product()],
            [source],
            client=client,
        )


def test_synthesis_does_not_treat_a_model_code_as_a_measurable_claim():
    source = evidence().model_copy(
        update={"text": "Active noise cancellation designed for travel."}
    )
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC (FL-48) is the travel choice [1]."
    )

    answer, citations, _ = synthesize_cited_answer(
        "What should I use on a long flight?",
        [product()],
        [source],
        client=client,
    )

    assert "FL-48" in answer
    assert [record.product_id for record in citations] == [101]


def test_synthesis_rejects_numeric_support_borrowed_from_another_product():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-60",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
            "text": "60-hour battery life for office use.",
        }
    )
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC provides 60-hour battery life [1][2]. "
        "AuriLogic Office ANC is the office alternative [2]."
    )

    with pytest.raises(ValueError, match="unsupported numeric claim.*60.*product 101"):
        synthesize_cited_answer(
            "Compare the options.",
            [product(), second_product],
            [evidence(), second_evidence],
            client=client,
        )


def test_synthesis_accepts_product_scoped_numbers_in_a_comparison():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-60",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
            "text": "60-hour battery life for office use.",
        }
    )
    client = FakeSynthesisClient(
        "AuriLogic Flight ANC provides 48-hour battery life, while "
        "AuriLogic Office ANC provides 60-hour battery life [1][2]."
    )

    answer, citations, _ = synthesize_cited_answer(
        "Compare the options.",
        [product(), second_product],
        [evidence(), second_evidence],
        client=client,
    )

    assert answer.startswith("AuriLogic Flight ANC provides 48-hour")
    assert [record.product_id for record in citations] == [101, 102]


def test_synthesis_assigns_pre_name_comparison_numbers_to_the_following_product():
    second_product = product().model_copy(
        update={
            "product_id": 102,
            "title": "AuriLogic Office ANC",
            "model": "OF-60",
        }
    )
    second_evidence = evidence().model_copy(
        update={
            "evidence_id": 9002,
            "product_id": 102,
            "title": "AuriLogic Office ANC specifications",
            "text": "60-hour battery life for office use.",
        }
    )
    client = FakeSynthesisClient(
        "At 48 hours, AuriLogic Flight ANC covers long trips, while at 60 hours, "
        "AuriLogic Office ANC lasts longer between charges [1][2]."
    )

    answer, citations, _ = synthesize_cited_answer(
        "Compare the options.",
        [product(), second_product],
        [evidence(), second_evidence],
        client=client,
    )

    assert answer.startswith("At 48 hours")
    assert [record.product_id for record in citations] == [101, 102]


def test_agent_finalizes_retrieved_products_when_orchestration_stops(monkeypatch):
    source = evidence()
    state = {
        "result_limit": 4,
        "products": {101: product()},
        "evidence": {source.evidence_id: source},
        "evidence_by_product": {101: [source.evidence_id]},
        "answer_of_record": None,
        "trace": [
            {
                "tool": "compare_products",
                "arguments": {"product_ids": [101]},
                "outcome": "success",
            }
        ],
    }
    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(
        agent_tools,
        "synthesize_answer",
        lambda *_args: (
            "Choose the quiet option [1].",
            [citation()],
            {"totalTokens": 42},
        ),
    )
    try:
        agent_tools.finalize_retrieved_answer("What should I buy?")
    finally:
        agent_tools._RUN.reset(token)

    assert state["answer_of_record"]["answer"] == "Choose the quiet option [1]."
    assert state["trace"][-1]["tool"] == "synthesize_cited_answer"
    assert state["trace"][-1]["origin"] == "controller_fallback"


def test_grounding_completion_uses_a_bounded_cross_search_shortlist(monkeypatch):
    search_event_id = uuid4()
    second = product().model_copy(
        update={"product_id": 102, "title": "AuriLogic Office ANC"}
    )
    third = product().model_copy(
        update={"product_id": 103, "title": "Mosaic Ergonomic Chair"}
    )
    fourth = product().model_copy(
        update={"product_id": 104, "title": "Mosaic Task Chair"}
    )
    state = {
        "result_limit": 6,
        "products": {
            item.product_id: item for item in (product(), second, third, fourth)
        },
        "evidence": {},
        "evidence_by_product": {},
        "answer_of_record": None,
        "trace": [],
        "search_event_ids": [search_event_id],
        "searches": [
            {"product_ids": [101, 102]},
            {"product_ids": [103, 104]},
        ],
    }
    evidence_calls: list[int] = []
    finalized: list[int] = []

    def read_evidence(product_id, evidence_query):
        evidence_calls.append(product_id)
        assert evidence_query == "Compare the options."
        state["evidence_by_product"][product_id] = [9000 + product_id]
        return {"ok": True}

    def finalize(_question, *, product_ids):
        finalized.extend(product_ids)

    def explain(event_id):
        assert event_id == str(search_event_id)
        state["trace"].append(
            {
                "tool": "explain_retrieval",
                "outcome": "success",
                "arguments": {"search_event_id": event_id},
            }
        )
        return {"ok": True}

    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(agent_tools, "get_product_evidence", read_evidence)
    monkeypatch.setattr(agent_tools, "explain_retrieval", explain)
    monkeypatch.setattr(agent_tools, "finalize_retrieved_answer", finalize)
    try:
        agent_tools.complete_grounded_answer("Compare the options.")
    finally:
        agent_tools._RUN.reset(token)

    assert evidence_calls == [101, 102, 103, 104]
    assert finalized == [101, 102, 103, 104]
    assert agent_tools._comparison_covers(state, finalized)
    assert [step["tool"] for step in state["trace"]].count("explain_retrieval") == 1


def test_grounding_completion_fails_when_evidence_is_not_attached(monkeypatch):
    state = {
        "result_limit": 2,
        "products": {101: product()},
        "evidence": {},
        "evidence_by_product": {},
        "answer_of_record": None,
        "trace": [],
        "searches": [{"product_ids": [101]}],
    }
    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(
        agent_tools,
        "get_product_evidence",
        lambda _product_id, _evidence_query: {"ok": True, "evidence": [evidence()]},
    )
    try:
        with pytest.raises(RuntimeError, match="No retrieved evidence"):
            agent_tools.complete_grounded_answer("What should I buy?")
    finally:
        agent_tools._RUN.reset(token)


def test_multi_product_synthesis_requires_a_successful_comparison():
    state = {
        "trace": [],
    }

    assert agent_tools._comparison_covers(state, [101, 102]) is False
    state["trace"].append(
        {
            "tool": "compare_products",
            "arguments": {"product_ids": [101, 102]},
            "outcome": "success",
        }
    )
    assert agent_tools._comparison_covers(state, [101, 102]) is True
    assert agent_tools._comparison_covers(state, [101, 102, 103]) is False


def test_agent_response_uses_turn_alias_and_search_event_trace():
    run_id = uuid4()
    search_event_id = uuid4()
    state = {
        "agent_run_id": run_id,
        "answer_of_record": {
            "answer": "Choose the quiet option [1].",
            "recommendations": [product()],
            "citations": [citation()],
        },
        "searches": [],
        "trace": [
            {
                "sequence": 1,
                "tool": "search_products",
                "detail": "Retrieved one product.",
                "search_event_id": search_event_id,
                "result_count": 1,
            }
        ],
    }

    response = ProductDiscoveryAgent()._response(
        AgentRequest(question="What should I buy?", result_limit=2),
        state,
        result=None,
        error=None,
    )

    assert response.agent_run_id == run_id
    assert response.trace[0].retrieval_run_id == search_event_id


def test_agent_prompt_resolves_followups_from_bounded_grounded_context():
    request = AgentRequest(
        question="Which one is the better value?",
        result_limit=2,
        context={
            "previous_question": "Find two travel headphones under $200.",
            "recommendations": [
                {
                    "product_id": 101,
                    "title": "AuriLogic Flight ANC",
                    "model": "FL-48",
                },
                {
                    "product_id": 102,
                    "title": "AuriLogic Office ANC",
                    "model": "OF-40",
                },
            ],
        },
    )

    prompt = _agent_prompt(request)

    assert '"Which one is the better value?"' in prompt
    assert '"product_id": 101' in prompt
    assert '"product_id": 102' in prompt
    assert "lookup targets only, not evidence" in prompt
    assert "Re-run the normal catalog retrieval" in prompt


def test_synchronous_agent_preserves_tool_run_context(monkeypatch):
    run_id = uuid4()
    source = evidence()
    state = {
        "agent_run_id": run_id,
        "agent_session_id": uuid4(),
        "agent_turn_id": run_id,
        "question": "What should I buy?",
        "base_filters": SearchFilters(),
        "result_limit": 2,
        "trace": [],
        "search_event_ids": [],
        "products": {101: product()},
        "evidence": {source.evidence_id: source},
        "evidence_by_product": {101: [source.evidence_id]},
        "searches": [],
        "answer_of_record": None,
    }

    def start_run(*_args):
        agent_tools._RUN.set(state)
        return state

    class FakeAgent:
        async def invoke_async(self, question):
            assert agent_tools._state() is state
            state["answer_of_record"] = {
                "answer": "Choose the quiet option [1].",
                "recommendations": [product()],
                "citations": [citation()],
                "usage": {},
            }
            return type("Result", (), {"metrics": {}})()

    monkeypatch.setattr(agent_tools, "start_run", start_run)
    monkeypatch.setattr("service.agent.build_agent", lambda: FakeAgent())
    monkeypatch.setattr(
        agent_tools, "persist_completed_run", lambda *_args, **_kwargs: None
    )

    response = ProductDiscoveryAgent().answer(
        AgentRequest(question="What should I buy?", result_limit=2)
    )

    assert response.agent_run_id == run_id
    assert response.citations[0].evidence_id == source.evidence_id


def test_agent_surfaces_grounding_contract_failure_over_model_loop_error(
    monkeypatch,
):
    state = {
        "agent_run_id": uuid4(),
        "products": {101: product()},
        "answer_of_record": None,
    }
    persisted_errors: list[str | None] = []

    class FailingAgent:
        async def invoke_async(self, _question):
            raise RuntimeError("model loop exhausted its token budget")

    def fail_grounding(_question):
        raise RuntimeError("No retrieved evidence is available for grounded synthesis")

    monkeypatch.setattr(agent_tools, "start_run", lambda *_args: state)
    monkeypatch.setattr("service.agent.build_agent", lambda: FailingAgent())
    monkeypatch.setattr(
        agent_tools,
        "complete_grounded_answer",
        fail_grounding,
    )
    monkeypatch.setattr(
        agent_tools,
        "persist_completed_run",
        lambda _state, **kwargs: persisted_errors.append(kwargs["error_type"]),
    )

    with pytest.raises(
        GroundingContractError,
        match="evidence and citation contract",
    ):
        ProductDiscoveryAgent().answer(
            AgentRequest(question="What should I buy?", result_limit=2)
        )

    assert persisted_errors == ["GroundingContractError"]


def test_strands_registers_the_read_only_product_tools():
    expected = {
        "search_products",
        "get_product_evidence",
        "compare_products",
        "explain_retrieval",
        "synthesize_cited_answer",
    }

    assert {tool.tool_name for tool in agent_tools.TOOL_FUNCTIONS} == expected
    assert set(build_agent().tool_registry.registry) == expected


def test_agent_uses_the_dedicated_model_override(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingModel:
        def __init__(self, **kwargs):
            captured["model_id"] = kwargs["model_id"]

    class CapturingAgent:
        def __init__(self, **kwargs):
            captured["agent_model"] = kwargs["model"]

    settings = replace(
        get_settings(),
        agent_model_id="global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    monkeypatch.setattr("service.agent.get_settings", lambda: settings)
    monkeypatch.setattr("service.agent.BedrockModel", CapturingModel)
    monkeypatch.setattr("service.agent.Agent", CapturingAgent)

    build_agent()

    assert captured["model_id"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_synthesis_uses_the_dedicated_model_override():
    settings = replace(
        get_settings(),
        synthesis_model_id="global.anthropic.claude-sonnet-5",
    )
    client = FakeSynthesisClient(
        "Summary\nChoose this option [1].\n\n"
        "Recommendations\n- AuriLogic Flight ANC is quiet [1].\n\n"
        "Trade-offs\nBattery life is not specified [1]."
    )

    synthesize_cited_answer(
        "Which option should I choose?",
        [product()],
        [evidence()],
        settings=settings,
        client=client,
    )

    assert client.request["modelId"] == "global.anthropic.claude-sonnet-5"


def test_agent_tool_filters_cannot_widen_request_filters():
    base = SearchFilters(
        domain="home_office",
        category_key="office-chairs",
        brand="Mosaic",
        availability="low_stock",
        in_stock_only=True,
        min_price_cents=20_000,
        max_price_cents=80_000,
        min_rating=4.0,
        attributes={"seat_depth_adjustable": True},
    )
    supplied = SearchFilters(
        domain="consumer_electronics",
        category_key="over-ear-headphones",
        brand="AuriLogic",
        availability="preorder",
        min_price_cents=10_000,
        max_price_cents=120_000,
        min_rating=3.0,
        attributes={
            "seat_depth_adjustable": False,
            "quiet_operation": True,
        },
    )

    merged = agent_tools._merge_search_filters(base, supplied)

    assert merged == SearchFilters(
        domain="home_office",
        category_key="office-chairs",
        brand="Mosaic",
        availability="low_stock",
        in_stock_only=True,
        min_price_cents=20_000,
        max_price_cents=80_000,
        min_rating=4.0,
        attributes={
            "seat_depth_adjustable": True,
            "quiet_operation": True,
        },
    )


def test_agent_tool_filters_may_narrow_request_filters():
    base = SearchFilters(
        domain="home_office",
        in_stock_only=True,
        min_price_cents=20_000,
        max_price_cents=80_000,
        min_rating=4.0,
    )
    supplied = SearchFilters(
        category_key="office-chairs",
        min_price_cents=30_000,
        max_price_cents=70_000,
        min_rating=4.5,
        attributes={"seat_depth_adjustable": True},
    )

    merged = agent_tools._merge_search_filters(base, supplied)

    assert merged == SearchFilters(
        domain="home_office",
        category_key="office-chairs",
        in_stock_only=True,
        min_price_cents=30_000,
        max_price_cents=70_000,
        min_rating=4.5,
        attributes={"seat_depth_adjustable": True},
    )


def test_agent_search_tool_enforces_its_two_search_budget():
    state = {"searches": [{}, {}]}
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.search_products.__wrapped__("another broad search")
    finally:
        agent_tools._RUN.reset(token)

    assert result == {
        "ok": False,
        "error": "search_products allows 2 searches per agent turn; found 2",
        "recovery": (
            "use the products already retrieved and call "
            "synthesize_cited_answer, or state the evidence gap."
        ),
    }


def test_agent_search_keeps_the_served_rank_order_before_evidence_retrieval(
    monkeypatch,
):
    """Evidence availability cannot rewrite product retrieval order."""
    ranked = [
        product().model_copy(update={"product_id": 301, "model": "First"}),
        product().model_copy(update={"product_id": 302, "model": "Second"}),
        product().model_copy(update={"product_id": 303, "model": "Third"}),
    ]
    response = SearchResponse(
        search_event_id=uuid4(),
        query="quiet office gear",
        normalized_query="quiet office gear",
        applied_filters={},
        results=ranked,
        diagnostics=None,
    )

    class FakeRetrieval:
        def search(self, request):
            assert request.limit == get_settings().rerank_candidate_limit
            return response

    state = {
        "base_filters": SearchFilters(),
        "result_limit": 3,
        "searches": [],
        "search_event_ids": [],
        "products": {},
        "trace": [],
    }
    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(agent_tools, "get_retrieval_service", lambda: FakeRetrieval())
    try:
        result = agent_tools.search_products.__wrapped__(
            "quiet office gear",
            limit=2,
        )
    finally:
        agent_tools._RUN.reset(token)

    assert result["ok"] is True
    assert [item["product_id"] for item in result["products"]] == [301, 302]
    assert state["searches"][0]["product_ids"] == [301, 302]
    assert [item.product_id for item in state["products"].values()] == [301, 302]


def test_evidence_tool_forwards_question_and_embedding_to_catalog(monkeypatch):
    expected_embedding = [0.125, 0.25]
    captured: dict[str, object] = {}

    class FakeRetrieval:
        def embed_query(self, query):
            captured["embedding_query"] = query
            return expected_embedding

    def read_evidence(product_id, query, embedding, *, limit):
        captured.update(
            product_id=product_id,
            query=query,
            embedding=embedding,
            limit=limit,
        )
        return [evidence()]

    state = {
        "products": {101: product()},
        "evidence": {},
        "evidence_by_product": {},
        "trace": [],
    }
    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(agent_tools, "get_retrieval_service", lambda: FakeRetrieval())
    monkeypatch.setattr(agent_tools, "get_product_evidence_records", read_evidence)
    try:
        result = agent_tools.get_product_evidence.__wrapped__(
            101,
            "Which fact supports long-flight comfort?",
        )
    finally:
        agent_tools._RUN.reset(token)

    assert result["ok"] is True
    assert captured == {
        "embedding_query": "Which fact supports long-flight comfort?",
        "product_id": 101,
        "query": "Which fact supports long-flight comfort?",
        "embedding": expected_embedding,
        "limit": len(agent_tools.SEARCH_SLOTS),
    }
    assert state["evidence_by_product"] == {101: [9001]}


def test_product_evidence_endpoint_uses_question_ranked_evidence(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRetrieval:
        def embed_query(self, query):
            captured["embedding_query"] = query
            return [0.125, 0.25]

    def read_evidence(product_id, query, embedding, *, limit):
        captured.update(
            product_id=product_id,
            query=query,
            embedding=embedding,
            limit=limit,
        )
        return [evidence()]

    monkeypatch.setattr("service.main.get_retrieval_service", lambda: FakeRetrieval())
    monkeypatch.setattr("service.main.get_product_evidence_records", read_evidence)

    client = TestClient(app)
    response = client.post(
        "/api/products/101/evidence",
        json={
            "evidence_query": "Which fact supports long-flight comfort?",
            "limit": 4,
        },
    )

    assert response.status_code == 200
    assert response.json()["product_id"] == 101
    assert response.json()["evidence"][0]["evidence_id"] == 9001
    assert captured == {
        "embedding_query": "Which fact supports long-flight comfort?",
        "product_id": 101,
        "query": "Which fact supports long-flight comfort?",
        "embedding": [0.125, 0.25],
        "limit": 4,
    }


def test_evidence_tool_surfaces_expired_bedrock_credentials(monkeypatch):
    class ExpiredRetrieval:
        def embed_query(self, _query):
            raise ClientError(
                {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}},
                "InvokeModel",
            )

    state = {
        "products": {101: product()},
        "evidence": {},
        "evidence_by_product": {},
        "trace": [],
    }
    token = agent_tools._RUN.set(state)
    monkeypatch.setattr(
        agent_tools,
        "get_retrieval_service",
        lambda: ExpiredRetrieval(),
    )
    try:
        with pytest.raises(
            ModelRuntimeError,
            match="Refresh the active AWS session and restart the API process",
        ):
            agent_tools.get_product_evidence.__wrapped__(
                101,
                "Which fact supports long-flight comfort?",
            )
    finally:
        agent_tools._RUN.reset(token)


def test_agent_api_reports_expired_bedrock_credentials_without_hiding_the_cause(
    monkeypatch,
):
    class ExpiredAgent:
        def answer(self, _request):
            raise ClientError(
                {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}},
                "Converse",
            )

    monkeypatch.setattr(
        "service.main.get_product_discovery_agent",
        lambda: ExpiredAgent(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/agent/answer",
        json={"question": "What should I buy?", "filters": {}, "result_limit": 2},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Amazon Bedrock credentials are unavailable (ExpiredTokenException). "
        "Refresh the active AWS session and restart the API process."
    )


def test_readiness_blocks_when_a_required_retrieval_artifact_is_missing(monkeypatch):
    monkeypatch.setattr(
        "service.main.readiness",
        lambda: {
            "schema_ready": True,
            "product_count": 500000,
            "embedded_product_count": 500000,
            "embedding_model_ids": ["us.cohere.embed-v4:0"],
            "premium_product_count": 120,
            "evidence_product_count": 500000,
            "missing_retrieval_indexes": ["product_document_fts_gin_idx"],
            "missing_retrieval_functions": [],
        },
    )
    monkeypatch.setattr(
        "service.main.bedrock_credentials_status",
        lambda _region: {"ready": True},
    )
    client = TestClient(app)

    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["database_ready"] is False
    assert response.json()["database"]["missing_retrieval_indexes"] == [
        "product_document_fts_gin_idx"
    ]


def test_readiness_does_not_expose_credential_exception_text(monkeypatch):
    sentinel = "SENSITIVE_CREDENTIAL_TRACE"

    class FailingSts:
        def get_caller_identity(self):
            raise RuntimeError(sentinel)

    monkeypatch.setattr(
        "service.model_runtime.boto3.client",
        lambda *_args, **_kwargs: FailingSts(),
    )
    monkeypatch.setattr(
        "service.main.readiness",
        lambda: {
            "schema_ready": True,
            "product_count": 500000,
            "embedded_product_count": 500000,
            "embedding_model_ids": ["us.cohere.embed-v4:0"],
            "premium_product_count": 120,
            "evidence_product_count": 500000,
            "missing_retrieval_indexes": [],
            "missing_retrieval_functions": [],
        },
    )

    response = TestClient(app).get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert sentinel not in response.text
    assert response.json()["bedrock_credentials"]["error"] == (
        "AWS credential validation failed. Refresh the active AWS session and "
        "restart the API process."
    )


def test_readiness_sql_requires_artifacts_in_the_mosaic_search_schema():
    source = (ROOT / "service/db.py").read_text(encoding="utf-8")

    assert "index_schema.nspname = 'mosaic_search'" in source
    assert "namespace.nspname = 'mosaic_search'" in source
    assert "WHERE NOT EXISTS (" in source


def test_public_runtime_contracts_are_inspectable():
    client = TestClient(app)

    health = client.get("/api/health")
    tools = client.get("/api/tools")
    projection = client.get("/api/benchmarks/projection")

    assert health.status_code == 200
    assert health.json()["models"]["embedding"] == "us.cohere.embed-v4:0"
    assert tools.status_code == 200
    assert all(item["read_only"] for item in tools.json()["tools"])
    assert projection.status_code == 200
    assert projection.json()["assumptions"]["dimensions"] == 1024


def test_agent_stream_forwards_strands_tool_stages_and_validated_answer(monkeypatch):
    response = AgentResponse(
        agent_run_id=uuid4(),
        question="What should I buy?",
        answer="Summary\nChoose the quiet option [1].",
        plan=[],
        recommendations=[product()],
        citations=[citation()],
        trace=[],
    )

    class FakeStreamingAgent:
        async def stream(self, _request):
            yield {"current_tool_use": {"name": "search_products"}}
            yield {"current_tool_use": {"name": "compare_products"}}
            yield {"current_tool_use": {"name": "synthesize_cited_answer"}}
            yield {"agent_response": response}

    monkeypatch.setattr(
        "service.main.get_product_discovery_agent",
        lambda: FakeStreamingAgent(),
    )
    client = TestClient(app)

    stream = client.post(
        "/api/agent/answer/stream",
        json={"question": "What should I buy?", "filters": {}, "result_limit": 2},
    )

    assert stream.status_code == 200
    assert "event: stage" in stream.text
    assert '"id": "retrieve"' in stream.text
    assert '"id": "rank"' in stream.text
    assert "event: answer_delta" in stream.text
    assert "event: complete" in stream.text
    assert "Choose the quiet option [1]." in stream.text


def test_agent_stream_does_not_expose_exception_text(monkeypatch):
    sentinel = "SENSITIVE_AGENT_STACK"

    class FailingStreamingAgent:
        async def stream(self, _request):
            if False:
                yield {}
            raise RuntimeError(sentinel)

    monkeypatch.setattr(
        "service.main.get_product_discovery_agent",
        lambda: FailingStreamingAgent(),
    )

    stream = TestClient(app).post(
        "/api/agent/answer/stream",
        json={"question": "What should I buy?", "filters": {}, "result_limit": 2},
    )

    assert stream.status_code == 200
    assert "event: error" in stream.text
    assert sentinel not in stream.text
    assert "RuntimeError" not in stream.text
    assert (
        "Agent response failed. Retry after checking the runtime and retrieval service."
    ) in stream.text


def test_retrieval_sql_casts_python_values_to_the_function_contract():
    source = (ROOT / "service/retrieval.py").read_text()

    # PostgreSQL type modifiers cannot be bind parameters (`vector($1)` is a
    # syntax error). The called function owns the rendered vector width.
    assert "%(embedding)s::vector" in source
    assert "::vector(%(dims)s)" not in source
    assert "%(rrf_k)s::integer" in source
    assert "%(business_weight)s::real" not in source
    assert "ORDER BY h.pre_rerank_score DESC, h.product_id" in source
    assert "'error_type', %s::text" in source
