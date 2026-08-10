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


def test_tool_call_against_the_real_app_does_not_404():
    """End-to-end: send the MCP client's exact request into the real app.

    `httpx.ASGITransport` is async-only, so the sync client cannot drive it.
    `TestClient` runs the same ASGI app and is what the rest of the suite uses;
    routing is what is under test here, not the client's transport plumbing.
    """
    from fastapi.testclient import TestClient

    match = re.search(r'get\(f"(/retrieval/[^"]*)\{parsed_run_id\}"\)', SERVER_SOURCE)
    assert match, "inspect_retrieval_run must build its path from parsed_run_id"
    tool_path = f"/api{match.group(1)}{uuid4()}"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(tool_path)
    # No database is configured here, so the handler cannot return a payload.
    # What matters is that routing resolved: 404 would mean the path is wrong.
    assert response.status_code != 404, (
        f"MCP tool requests {tool_path}, which the API does not route"
    )
