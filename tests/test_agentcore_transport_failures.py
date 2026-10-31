"""Transport faults that must reach the participant as a setup step or an error frame."""

import io
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from service import agentcore_transport as transport

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/MosaicAgent_example"
SHA = "a" * 64


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(
        "service.lab_validation_receipt.application_digest", lambda: SHA
    )
    monkeypatch.setattr("scripts.lab_state.lab_source_is_repaired", lambda lab: True)
    monkeypatch.setattr("scripts.lab_state.lab3_problem", lambda **_: None)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", ARN)
    client = Mock()
    client.invoke_agent_runtime.side_effect = lambda **_: {
        "response": io.BytesIO(b"{}")
    }
    monkeypatch.setattr(transport, "runtime_client", lambda: client)
    return client


@pytest.mark.parametrize("route", ["/api/agent/answer/stream", "/api/agent/answer"])
def test_a_missing_agent_file_is_a_setup_step_not_a_500(monkeypatch, runtime, route):
    """Deleting labs/lab3_reason/agent.py made the digest or contract check raise OSError."""
    from service.main import app

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("labs/lab3_reason/agent.py")

    monkeypatch.setattr("service.lab_validation_receipt.application_digest", missing)
    response = TestClient(app, raise_server_exceptions=False).post(
        route, json={"question": "A monitor", "filters": {}}
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "agent_setup"
    assert "lab_state.py reset --lab 3" in body["detail"]
    runtime.invoke_agent_runtime.assert_not_called()


@pytest.mark.parametrize("route", ["/api/agent/answer/stream", "/api/agent/answer"])
@pytest.mark.parametrize(
    "content", ["[]", '{"version": 1, "lab": 3, "completed_at": 5}']
)
def test_an_unreadable_lab_3_start_record_is_a_setup_step(
    source, runtime, route, content
):
    """A list or a non-string timestamp raised AttributeError or TypeError past the handler."""
    from service import agent_deploys
    from service.main import app

    path = agent_deploys.ROOT / ".local" / "lab-3" / "start.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    response = TestClient(app, raise_server_exceptions=False).post(
        route, json={"question": "A monitor", "filters": {}}
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "agent_setup"
    assert "lab_state.py reset --lab 3" in body["detail"]
    runtime.invoke_agent_runtime.assert_not_called()


def test_a_cut_runtime_stream_ends_with_an_error_frame(monkeypatch):
    """After headers are sent a status is impossible, so the stream must say it broke."""

    class Cut:
        def __init__(self):
            self.chunks = [b'event: tool\ndata: {"name": "search_products"}\n\n']

        def read1(self, _size):
            if self.chunks:
                return self.chunks.pop(0)
            raise ConnectionResetError("secret detail the shopper must not see")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    frames = list(transport._as_received(Cut()))
    assert frames[0].startswith(b"event: tool")
    last = frames[-1].decode()
    name, data = last.split("\n", 1)
    assert name == "event: error"
    payload = json.loads(data.removeprefix("data: "))
    assert payload == {
        "status": 503,
        "detail": "Retrieval agent stream was interrupted; ask again",
    }
    assert "secret" not in last
