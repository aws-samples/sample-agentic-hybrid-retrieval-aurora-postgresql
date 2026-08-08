from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from mcp import Client
from starlette.testclient import TestClient

from catalog_mcp.api import CatalogApiClient, CatalogApiError
from catalog_mcp import server


class FakeCatalogApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", path, payload))
        return {
            "run_id": str(uuid4()),
            "query": payload["query"],
            "normalized_query": payload["query"].lower(),
            "applied_filters": payload["filters"],
            "results": [],
            "diagnostics": {
                "strategy": "hybrid_rrf_rerank",
                "embedding_model_id": "us.cohere.embed-v4:0",
                "rerank_model_id": "cohere.rerank-v3-5:0",
                "rerank_status": "applied",
                "rrf_k": 60,
                "arm_weights": {
                    "lexical": 0.30,
                    "trigram": 0.10,
                    "semantic": 0.45,
                },
                "candidate_counts": {
                    "lexical": 20,
                    "trigram": 15,
                    "semantic": 30,
                },
                "stage_timings_ms": {"total": 18.4},
                "total_latency_ms": 18,
            },
        }

    def get(self, path: str) -> dict[str, Any]:
        self.calls.append(("GET", path, None))
        raise AssertionError(f"Unexpected GET {path}")


@pytest.mark.anyio
async def test_mcp_negotiates_2026_protocol_and_calls_canonical_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeCatalogApi()
    monkeypatch.setattr(server, "get_api_client", lambda: api)

    async with Client(server.mcp, mode="auto") as client:
        assert client.protocol_version == "2026-07-28"
        listing = await client.list_tools()
        tools = {tool.name: tool for tool in listing.tools}

        assert set(tools) == {
            "search_products",
            "get_product_evidence",
            "inspect_retrieval_run",
        }
        assert all(tool.annotations.read_only_hint for tool in tools.values())
        assert (
            tools["search_products"]
            .input_schema["properties"]["domain"]["anyOf"][0]["enum"]
            == [
                "consumer_electronics",
                "running_fitness",
                "home_office",
            ]
        )

        result = await client.call_tool(
            "search_products",
            {
                "query": "quiet headphones for long flights",
                "domain": "consumer_electronics",
                "max_price": 200,
                "limit": 6,
            },
        )

    assert result.is_error is False
    assert result.structured_content["diagnostics"]["rrf_k"] == 60
    assert api.calls == [
        (
            "POST",
            "/search",
            {
                "query": "quiet headphones for long flights",
                "filters": {
                    "domain": "consumer_electronics",
                    "max_price": 200.0,
                },
                "limit": 6,
                "include_diagnostics": True,
                "rerank": True,
            },
        )
    ]


def _modern_request(
    method: str,
    *,
    request_id: int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "catalog-contract-test",
                    "version": "1.0",
                },
            },
        },
    }


def test_stateless_http_discovery_and_routing_headers() -> None:
    app = server.create_http_app(host="testserver")
    with TestClient(app) as client:
        discovery = client.post(
            "/mcp",
            json=_modern_request("server/discover", request_id=1),
            headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "server/discover",
            },
        )
        missing_name = client.post(
            "/mcp",
            json=_modern_request(
                "tools/call",
                request_id=2,
                params={
                    "name": "search_products",
                    "arguments": {"query": "quiet headphones"},
                },
            ),
            headers={
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
            },
        )

    assert discovery.status_code == 200
    assert discovery.json()["result"]["supportedVersions"] == ["2026-07-28"]
    assert "mcp-session-id" not in discovery.headers
    assert missing_name.status_code == 400
    assert missing_name.json()["error"]["code"] == -32020


def test_catalog_api_client_sanitizes_http_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"internal": "do not expose"})

    client = CatalogApiClient(
        "http://catalog.test/api",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        CatalogApiError,
        match=r"HTTP 503 for POST /search",
    ):
        client.post("/search", {"query": "test"})
