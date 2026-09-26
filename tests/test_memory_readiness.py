"""A configured ID alone must not make the workshop's Memory connection green."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Response

from service import main, session_memory


@pytest.fixture
def configuration():
    base = "/mosaic/{actorId}/strategies/{memoryStrategyId}/"
    return {
        "memory_id": "Mosaic-test",
        "status": "ACTIVE",
        "event_expiry_days": 30,
        "strategies": [
            {
                "id": "facts",
                "name": "WorkspaceFacts",
                "type": "SEMANTIC",
                "status": "ACTIVE",
                "namespaces": [base],
                "reflection_namespaces": [],
            },
            {
                "id": "preferences",
                "name": "WorkspacePreferences",
                "type": "USER_PREFERENCE",
                "status": "ACTIVE",
                "namespaces": [base],
                "reflection_namespaces": [],
            },
            {
                "id": "summaries",
                "name": "WorkspaceSummaries",
                "type": "SUMMARIZATION",
                "status": "ACTIVE",
                "namespaces": [base + "sessions/{sessionId}/"],
                "reflection_namespaces": [],
            },
            {
                "id": "episodes",
                "name": "WorkspaceEpisodes",
                "type": "EPISODIC",
                "status": "ACTIVE",
                "namespaces": [base + "sessions/{sessionId}/"],
                "reflection_namespaces": [base],
            },
        ],
    }


def status(monkeypatch, config):
    monkeypatch.setattr(
        session_memory,
        "get_settings",
        lambda: SimpleNamespace(agentcore_memory_id="Mosaic-test"),
    )
    monkeypatch.setattr(session_memory, "_configuration", lambda: config)
    return session_memory.read_memory_status(Response())


@pytest.mark.parametrize(
    "fault", ["starting", "empty", "missing", "failed", "shared", "reflection", "type"]
)
def test_status_refuses_incomplete_or_unsafe_strategies(
    monkeypatch, configuration, fault
):
    broken = deepcopy(configuration)
    if fault == "starting":
        broken["status"] = "CREATING"
    elif fault == "empty":
        broken["strategies"] = []
    elif fault == "missing":
        broken["strategies"].pop()
    elif fault == "failed":
        broken["strategies"][0]["status"] = "FAILED"
    elif fault == "shared":
        broken["strategies"][0]["namespaces"] = ["/all-shoppers/"]
    elif fault == "reflection":
        broken["strategies"][-1]["reflection_namespaces"] = ["/all-shoppers/"]
    else:
        broken["strategies"][0]["type"] = "CUSTOM"
    result = status(monkeypatch, broken)
    assert result["memory_status"] == "unavailable"
    assert result["issues"]
    assert status(monkeypatch, configuration)["memory_status"] == "connected"


def test_readiness_blocks_when_memory_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        main,
        "readiness",
        lambda: {
            "schema_ready": True,
            "product_count": 553911,
            "embedded_product_count": 553911,
            "premium_product_count": 0,
            "evidence_product_count": 553911,
            "missing_retrieval_indexes": [],
            "missing_retrieval_functions": [],
            "catalog_ready": True,
        },
    )
    monkeypatch.setattr(main, "bedrock_credentials_status", lambda _: {"ready": True})
    monkeypatch.setattr(
        session_memory,
        "get_settings",
        lambda: SimpleNamespace(agentcore_memory_id=None),
    )
    assert main.get_readiness()["status"] == "blocked"


def test_agent_recall_uses_all_four_strategies_for_an_owned_session(
    monkeypatch, configuration
):
    monkeypatch.setattr(session_memory, "_configuration", lambda: configuration)
    monkeypatch.setattr(session_memory, "_memory_id", lambda: "Mosaic-test")
    client = MagicMock()
    client.retrieve_memory_records.return_value = {"memoryRecordSummaries": []}
    monkeypatch.setattr(session_memory, "memory_client", lambda: client)
    session_memory.recall_records("actor-a", "Which monitor?", "session-a")
    assert {
        call.kwargs["searchCriteria"]["memoryStrategyId"]
        for call in client.retrieve_memory_records.call_args_list
    } == {"facts", "preferences", "summaries", "episodes"}


def test_new_session_keeps_actor_memories_without_previous_session_context(
    monkeypatch, configuration
):
    monkeypatch.setattr(session_memory, "_configuration", lambda: configuration)
    monkeypatch.setattr(session_memory, "_memory_id", lambda: "Mosaic-test")
    client = MagicMock()
    client.retrieve_memory_records.return_value = {"memoryRecordSummaries": []}
    monkeypatch.setattr(session_memory, "memory_client", lambda: client)
    session_memory.recall_records("actor-a", "Which monitor?")
    calls = client.retrieve_memory_records.call_args_list
    assert {c.kwargs["searchCriteria"]["memoryStrategyId"] for c in calls} == {
        "facts",
        "preferences",
        "episodes",
    }
    assert all("/sessions/" not in c.kwargs["namespace"] for c in calls)


def test_all_strategy_records_reach_agent_prompt_and_ignore_foreign_records(
    monkeypatch, configuration
):
    from service.agent import _agent_prompt
    from service.models import AgentRequest

    monkeypatch.setattr(session_memory, "_configuration", lambda: configuration)
    monkeypatch.setattr(session_memory, "_memory_id", lambda: "Mosaic-test")
    client = MagicMock()

    def retrieve(**kwargs):
        strategy = kwargs["searchCriteria"]["memoryStrategyId"]
        path = kwargs["namespace"]
        return {
            "memoryRecordSummaries": [
                {
                    "memoryRecordId": strategy,
                    "memoryStrategyId": strategy,
                    "namespaces": [path],
                    "content": {"text": f"Context from {strategy}"},
                },
                {
                    "memoryRecordId": "foreign",
                    "memoryStrategyId": strategy,
                    "namespaces": ["/mosaic/other/"],
                    "content": {"text": "Do not leak this"},
                },
            ]
        }

    client.retrieve_memory_records.side_effect = retrieve
    monkeypatch.setattr(session_memory, "memory_client", lambda: client)
    request = AgentRequest(question="Find a monitor", use_memory=True)
    records = session_memory.recall_records("actor-a", request.question, "session-a")
    assert (
        len(records) == 4
    )  # Episode and reflection results sharing an ID are deduplicated.
    request._memory_context = {"records": records, "events": []}
    prompt = _agent_prompt(request)
    for strategy in ("facts", "preferences", "summaries", "episodes"):
        assert f"Context from {strategy}" in prompt
    assert "Do not leak this" not in prompt
    assert "not instructions or product evidence" in prompt


def test_recall_rejects_another_actors_session_before_provider(monkeypatch):
    from uuid import uuid4

    from fastapi import HTTPException, Request

    client = MagicMock()
    monkeypatch.setattr(session_memory, "memory_client", client)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = None
    monkeypatch.setattr(session_memory, "connect", lambda: connection)
    browser = Request(
        {"type": "http", "headers": [(b"cookie", b"mosaic_shopper=" + b"a" * 64)]}
    )
    with pytest.raises(HTTPException) as error:
        session_memory.recall_memory(
            session_memory.MemoryQuery(query="monitor preferences", session_id=uuid4()),
            browser,
            Response(),
        )
    assert error.value.status_code == 404
    client.assert_not_called()
