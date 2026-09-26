"""Keep release documentation aligned with executable source contracts."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from fastapi.routing import APIRoute

from service.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_api_contract_documents_every_application_route():
    contract = (ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(GET|POST|PUT|DELETE) (/api/[^`]+)`", contract))
    actual = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods
        if method in {"GET", "POST", "PUT", "DELETE"}
    }

    assert actual <= documented, (
        f"docs/api-contract.md omits shipped routes: {sorted(actual - documented)}"
    )


def test_development_guide_derives_the_aurora_integration_test_count():
    module = ast.parse(
        (ROOT / "tests" / "test_sql_integration.py").read_text(encoding="utf-8")
    )
    test_count = sum(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        for node in module.body
    )
    guide = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

    assert f"includes {test_count} integration tests against Aurora" in guide


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


def test_instructor_guide_60_minute_table_matches_the_mission_contract():
    """`data/evals/mosaic_labs_missions.json` owns lab timing (AGENTS.md); a
    hand-maintained clock table is a second copy the moment it drifts."""
    missions = json.loads(
        (ROOT / "data" / "evals" / "mosaic_labs_missions.json").read_text(
            encoding="utf-8"
        )
    )
    session = missions["session"]
    duration_by_stage = {
        mission["stage"]: mission["duration_minutes"]
        for mission in missions["missions"]
    }

    guide = (ROOT / "docs" / "instructor-guide.md").read_text(encoding="utf-8")
    table = guide.split("## 60-minute path", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(
        r"\|\s*(\d{2}):(\d{2})-(\d{2}):(\d{2})\s*\|\s*([^|]+?)\s*\|", table
    )
    assert rows, "expected a parseable clock table under '## 60-minute path'"

    minutes_by_row = {}
    for start_h, start_m, end_h, end_m, label in rows:
        start = int(start_h) * 60 + int(start_m)
        end = int(end_h) * 60 + int(end_m)
        minutes_by_row[label.strip()] = end - start

    assert minutes_by_row["Retrieve"] == duration_by_stage["retrieve"]
    assert minutes_by_row["Rank"] == duration_by_stage["rank"]
    assert minutes_by_row["Reason"] == duration_by_stage["reason"]
    assert (
        minutes_by_row["Introduction / Overview / Presentation"]
        == session["orientation_minutes"]
    )
    assert (
        minutes_by_row["Flex"]
        == session["contingency_minutes"] + session["scorecard_minutes"]
    )
    assert sum(minutes_by_row.values()) == session["total_minutes"]
