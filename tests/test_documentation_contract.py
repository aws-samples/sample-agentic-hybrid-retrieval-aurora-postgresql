"""Keep release documentation aligned with executable source contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fastapi.routing import APIRoute

from service.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_api_contract_documents_every_application_route():
    contract = (ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(GET|POST) (/api/[^`]+)`", contract))
    actual = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods
        if method in {"GET", "POST"}
    }

    assert actual <= documented, (
        f"docs/api-contract.md omits shipped routes: {sorted(actual - documented)}"
    )


def test_readme_derives_the_aurora_integration_test_count():
    module = ast.parse(
        (ROOT / "tests" / "test_sql_integration.py").read_text(encoding="utf-8")
    )
    test_count = sum(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        for node in module.body
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"includes {test_count} read-only integration tests against Aurora" in readme


def test_readiness_places_the_python_gate_under_aurora():
    readiness = (ROOT / "READINESS.md").read_text(encoding="utf-8")
    repository_gates, aurora_and_after = readiness.split("## Aurora-backed gates", 1)
    aurora_gates = aurora_and_after.split("## Clean-account acceptance test", 1)[0]

    assert "make test" not in repository_gates
    assert "make test" in aurora_gates


def test_media_docs_close_the_completed_replacement_work():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    regeneration = (ROOT / "docs" / "media-regeneration-batches.md").read_text(
        encoding="utf-8"
    )

    assert "four still outstanding" not in readme
    assert "OUTSTANDING" not in regeneration
    assert "All 13 wrong-subject images" in regeneration


def test_api_contract_pins_the_scorecard_pending_prefix():
    from service.scorecard import PENDING_TEXT

    contract = (ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    assert f"`{PENDING_TEXT}`" in contract
    assert "source_revision` equals" not in contract
