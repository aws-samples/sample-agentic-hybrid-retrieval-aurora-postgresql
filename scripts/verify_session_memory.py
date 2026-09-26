"""Prove Memory access through Mosaic's HTTP routes and runtime identity.

Creates an isolated deployment-check actor. It checks event persistence and all
strategy read paths, not asynchronous extraction quality or model responses.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from uuid import uuid4

import httpx


def verify(client: httpx.Client, memory_id: str) -> None:
    """Fail on a wrong resource, lost event, denied read, or broken actor isolation."""

    def request(method: str, path: str, **kwargs) -> dict:
        response = client.request(method, "/api/session-memory" + path, **kwargs)
        if response.is_error:
            raise RuntimeError(
                f"Memory acceptance: {method} {path} returned {response.status_code}; check API logs and the runtime role's Memory permissions."
            )
        return response.json() if response.content else {}

    status = request("GET", "/status")
    config = status.get("configuration") or {}
    if (
        status.get("memory_status") != "connected"
        or config.get("memory_id") != memory_id
    ):
        raise RuntimeError(
            f"Memory acceptance: status={status.get('memory_status')!r}, resource={config.get('memory_id')!r}; check the stack's Memory ID and strategy readiness."
        )
    request("GET", "")
    message = "Mosaic deployment check: I prefer a monitor with one USB-C cable."
    saved = request(
        "POST", "/events", json={"text": message, "request_id": str(uuid4())}
    )
    session = saved["session_id"]
    for attempt in range(12):
        events = request("GET", "/events", params={"session_id": session})["events"]
        if any(
            e["id"] == saved["event_id"]
            and {"role": "USER", "text": message} in e["messages"]
            for e in events
        ):
            break
        if attempt == 11:
            raise RuntimeError(
                "Memory acceptance: saved event was not readable after 30 seconds; inspect AgentCore event access and persistence."
            )
        time.sleep(2.5)
    for strategy in config["strategies"]:
        records = request(
            "GET",
            "/records",
            params={"strategy_id": strategy["id"], "session_id": session},
        )
        if not records.get("namespaces"):
            raise RuntimeError(
                f"Memory acceptance: {strategy['name']} has no readable namespace; restore its actor/session template."
            )
    request(
        "POST",
        "/recall",
        json={"query": "What monitor do I prefer?", "session_id": session},
    )
    request("POST", "/reset")
    response = client.get("/api/session-memory/events", params={"session_id": session})
    if response.status_code != 404:
        raise RuntimeError(
            f"Memory acceptance: a new actor reading the old session returned {response.status_code}; restore session ownership enforcement."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--memory-id", required=True)
    args = parser.parse_args()
    secret = os.environ.get("MOSAIC_ORIGIN_VERIFY_SECRET")
    headers = {"X-Mosaic-Origin-Verify": secret} if secret else {}
    try:
        with httpx.Client(
            base_url=args.api.rstrip("/"), headers=headers, timeout=90
        ) as client:
            verify(client, args.memory_id)
    except (RuntimeError, httpx.HTTPError, KeyError, ValueError) as error:
        # HTTP exceptions may contain the request; never print their headers.
        print(
            str(error)
            if isinstance(error, RuntimeError)
            else f"Memory acceptance failed ({type(error).__name__}); inspect the API and retry.",
            file=sys.stderr,
        )
        return 1
    print(
        "Memory acceptance passed: event saved and read, four strategy read paths, recall and actor isolation. Extraction is asynchronous."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
