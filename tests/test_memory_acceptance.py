"""Witnesses for the deployment probe: HTTP success alone is not acceptance."""

import json
import re
from pathlib import Path

import httpx
import pytest

from scripts.verify_session_memory import verify


def test_bootstrap_memory_cookie_round_trips_without_weakening_https():
    """The real cookie producer and HTTPX jar must agree on the probe scheme."""
    from fastapi import HTTPException, Request, Response

    from service.session_memory import _actor, shopper_id

    bootstrap = (Path(__file__).parents[1] / "deploy/mosaic-bootstrap.sh").read_text()
    api = re.search(r"--api (\S+) --memory-id", bootstrap)[1]

    def round_trip(base_url):
        def handle(request):
            # This is nginx's production scheme forwarding, including local probes.
            scheme = "https" if request.url.port == 8081 else request.url.scheme
            incoming = Request(
                {
                    "type": "http",
                    "method": request.method,
                    "path": "/",
                    "scheme": scheme,
                    "headers": [
                        (key.lower(), value) for key, value in request.headers.raw
                    ],
                }
            )
            response = Response()
            if request.method == "GET":
                shopper_id(incoming, response)
            else:
                try:
                    _actor(incoming)
                except HTTPException as error:
                    return httpx.Response(error.status_code)
            return httpx.Response(200, headers=response.headers)

        with httpx.Client(
            base_url=base_url, transport=httpx.MockTransport(handle)
        ) as client:
            client.get("/")
            secure = next(iter(client.cookies.jar)).secure
            return client.post("/").status_code, secure

    assert round_trip("http://127.0.0.1:8081") == (409, True)
    assert round_trip("https://mosaic.example") == (200, True)
    assert round_trip(api) == (200, False)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong_resource",
        "lost_event",
        "read_denied",
        "recall_denied",
        "actor_leak",
    ],
)
def test_probe_checks_storage_permissions_and_actor_boundary(monkeypatch, fault):
    monkeypatch.setattr("scripts.verify_session_memory.time.sleep", lambda _: None)
    state = {"reset": False, "message": None, "strategy_reads": []}

    def handle(request):
        path = request.url.path.removeprefix("/api/session-memory")
        payload = {}
        code = 200
        if path == "/status":
            payload = {
                "memory_status": "connected",
                "configuration": {
                    "memory_id": "other" if fault == "wrong_resource" else "memory",
                    "strategies": [
                        {"id": name, "name": name}
                        for name in ("facts", "preferences", "summaries", "episodes")
                    ],
                },
            }
        elif path == "/events" and request.method == "POST":
            state["message"] = json.loads(request.content)["text"]
            payload = {"session_id": "session", "event_id": "event"}
        elif path == "/events":
            payload = {
                "events": []
                if fault == "lost_event"
                else [
                    {
                        "id": "event",
                        "messages": [{"role": "USER", "text": state["message"]}],
                    }
                ]
            }
            if state["reset"] and fault != "actor_leak":
                code = 404
        elif path == "/records":
            state["strategy_reads"].append(request.url.params["strategy_id"])
            payload = {"namespaces": ["/actor/strategy/"], "records": []}
            code = 503 if fault == "read_denied" else 200
        elif path == "/recall":
            assert json.loads(request.content)["session_id"] == "session"
            code = 503 if fault == "recall_denied" else 200
            payload = {"records": []}
        elif path == "/reset":
            state["reset"] = True
        return httpx.Response(code, json=payload)

    with httpx.Client(
        base_url="http://mosaic.test", transport=httpx.MockTransport(handle)
    ) as client:
        if fault:
            with pytest.raises(RuntimeError, match="Memory acceptance:"):
                verify(client, "memory")
        else:
            verify(client, "memory")
            assert set(state["strategy_reads"]) == {
                "facts",
                "preferences",
                "summaries",
                "episodes",
            }
