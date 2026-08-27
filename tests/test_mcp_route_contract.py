"""The MCP tool has to request a path the API actually serves.

`inspect_retrieval_run` requested `/retrieval/runs/{run_id}` while the API serves
`/api/retrieval/events/{search_event_id}`, so the tool returned HTTP 404 on every
call. The existing MCP contract tests are source-text assertions, so nothing
exercised the URL. These checks resolve the request against the real FastAPI
route table instead of against a hand-written fake.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from service.main import app

ROOT = Path(__file__).resolve().parents[1]
SERVER_SOURCE = (ROOT / "mcp-server" / "catalog_mcp" / "server.py").read_text()


def _served_paths() -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


def _route_exists(path: str) -> bool:
    """True when a concrete path matches one of the app's route templates."""
    for template in _served_paths():
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        if re.fullmatch(pattern, path):
            return True
    return False


def test_the_api_serves_the_retrieval_event_route():
    assert "/api/retrieval/events/{search_event_id}" in _served_paths()


def test_the_api_serves_the_query_grounded_product_evidence_route():
    assert "/api/products/{product_id}/evidence" in _served_paths()


def test_mcp_evidence_tool_forwards_the_retrieval_scope():
    """The adapter must send the scope, and must not decide scope itself."""
    match = re.search(
        r'post\(\s*f"(/products/\{product_id\}/evidence)"\s*,\s*\{\s*'
        r'"retrieval_scope_id": retrieval_scope_id,\s*'
        r'"evidence_query": evidence_query,?\s*\}',
        SERVER_SOURCE,
    )
    assert match, (
        "get_product_evidence must forward retrieval_scope_id and "
        "evidence_query to the question-ranked evidence route"
    )
    assert _route_exists("/api/products/101/evidence")


def test_mcp_adapter_holds_no_scope_policy():
    """Enforcement belongs to service/retrieval_scope.py, not to a transport.

    The absence checks below would pass just as readily on an empty or
    gutted `server.py`, so they are preceded by positive assertions that the
    adapter still defines its three tools and that `get_product_evidence`
    still forwards `retrieval_scope_id` -- the same shape of check
    `test_mcp_evidence_tool_forwards_the_retrieval_scope` uses above.
    """
    for tool_name in (
        "search_products",
        "get_product_evidence",
        "inspect_retrieval_run",
    ):
        assert re.search(rf"\bdef {tool_name}\(", SERVER_SOURCE), (
            f"the MCP adapter no longer defines {tool_name!r}; a deleted or "
            "gutted adapter must not pass this test by omission"
        )

    match = re.search(
        r'post\(\s*f"(/products/\{product_id\}/evidence)"\s*,\s*\{\s*'
        r'"retrieval_scope_id": retrieval_scope_id,\s*'
        r'"evidence_query": evidence_query,?\s*\}',
        SERVER_SOURCE,
    )
    assert match, (
        "get_product_evidence must still forward retrieval_scope_id and "
        "evidence_query to the question-ranked evidence route"
    )

    for forbidden in ("authorized_limit", "result_rank", "search_result_event"):
        assert forbidden not in SERVER_SOURCE, (
            f"the MCP adapter references {forbidden!r}, which means it is "
            "making a grant-scope decision instead of forwarding the scope"
        )


def test_the_api_does_not_serve_the_path_the_tool_used_to_request():
    """If this ever starts passing, the fix below is no longer needed."""
    assert not _route_exists(f"/api/retrieval/runs/{uuid4()}")


def test_inspect_retrieval_run_requests_a_path_the_api_resolves():
    """Drive the real route shape: the tool's URL must not 404."""
    match = re.search(r'get\(f"(/retrieval/[^"]*)\{parsed_run_id\}"\)', SERVER_SOURCE)
    assert match, "inspect_retrieval_run must build its path from parsed_run_id"
    tool_path = f"{match.group(1)}{uuid4()}"

    # The client's base URL already carries `/api`, so that is the served path.
    assert _route_exists(f"/api{tool_path}"), (
        f"MCP tool requests /api{tool_path}, which the API does not serve"
    )


def test_no_shipped_source_or_doc_requests_the_dead_path():
    """Grep the shipped surfaces. The design spec and the gap ledger describe
    the defect by name, so they are the two files allowed to mention it."""
    allowed = {
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-08-09-phase1-stop-the-bleeding-design.md",
        ROOT / "docs" / "intentional-gaps.md",
        Path(__file__),
    }
    offenders = []
    for path in list(ROOT.rglob("*.md")) + list(ROOT.rglob("*.py")):
        if "node_modules" in path.parts or ".venv" in path.parts:
            continue
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The server comment names the dead path to explain the fix; only an
        # actual request to it is a defect.
        if 'get(f"/retrieval/runs/' in text or "/api/retrieval/runs/" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"dead path /retrieval/runs/ still requested in {offenders}"


def test_the_client_base_url_carries_the_api_prefix():
    """The tool paths are relative to it, so a change here breaks every tool."""
    import sys

    sys.path.insert(0, str(ROOT / "mcp-server"))
    from catalog_mcp.api import CatalogApiClient

    assert CatalogApiClient().base_url.endswith("/api")


def test_the_mcp_tool_path_is_a_route_the_app_declares():
    """The MCP client's path must resolve to a handler.

    Asserted against the app's declared routes rather than by sending a request.
    A request cannot answer this question: `retrieval_event` legitimately returns
    404 for an event that does not exist, so a status-code check conflates
    "unrouted path" with "unknown id" — and reads as a pass only when no database
    is configured, which is why it went green before Unit E supplied a DSN.
    """
    from fastapi.routing import APIRoute

    match = re.search(r'get\(f"(/retrieval/[^"]*)\{parsed_run_id\}"\)', SERVER_SOURCE)
    assert match, "inspect_retrieval_run must build its path from parsed_run_id"
    tool_template = f"/api{match.group(1)}{{search_event_id}}"

    declared = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert tool_template in declared, (
        f"MCP tool requests {tool_template}, which the API does not route; "
        f"declared retrieval routes: "
        f"{sorted(p for p in declared if '/retrieval/' in p)}"
    )


def test_an_unknown_retrieval_run_is_a_404_from_the_handler_not_the_router():
    """The two 404s must be distinguishable, or the route test above is hollow."""
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as client:
        known_route = client.get(f"/api/retrieval/events/{uuid4()}")
        no_such_route = client.get(f"/api/retrieval/invented/{uuid4()}")

    assert no_such_route.status_code == 404
    # A routed path reaches the handler: either the event is genuinely absent
    # (404 with the handler's own message) or the database is unreachable (503).
    if known_route.status_code == 404:
        assert known_route.json()["detail"] == "Search event not found"
    else:
        assert known_route.status_code in {200, 500, 503}
