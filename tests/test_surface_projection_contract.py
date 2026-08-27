"""Surface artifacts must describe only what that surface can accept and return.

House-standards.md rule 8: `db/config/agent_tool_contracts.json` models one
capability as a shared `payload_schema` plus per-surface `envelope_fields`, and
`output_schema` is the union of the payload and every envelope. That union is
correct for the canonical record. It became a lie the moment it was projected
verbatim into a surface-specific artifact: `render_database_sql()` copied the
full union into `db/sql/16_seed_tool_contracts.sql`, so the agent audit table
recorded a skill-only field (`retrieval_scope_id`) for `compare_products`, and
`contracts_for_surface()` served the same union to every surface over
`/api/tools`.

Three gates, each proving a different half of the fix:

1. The seeded SQL artifact itself carries only the agent envelope.
2. A live HTTP server -- not an in-process loader call -- carries only the
   requested surface's envelope, for all three surfaces.
3. Growing one surface's envelope changes only that surface's projection, and a
   witness proves the projection code actually ran rather than merely having
   nothing visible to disagree with.
"""

from __future__ import annotations

import contextlib
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts import tool_contracts
from scripts.tool_contracts import (
    CONTRACT_PATH,
    SQL_PATH,
    contracts_for_surface,
    render_database_sql,
)

ROOT = Path(__file__).resolve().parents[1]
_JSONB_BLOB = re.compile(r"'(\{.*?\})'::jsonb")


def _seeded_schemas(sql_text: str, tool_name: str) -> tuple[dict, dict]:
    """Parse a seeded row's (input_schema, output_schema) straight off disk.

    Reads the row exactly as `mosaic.agent_tool_contract` would receive it:
    no call into `render_database_sql()`, so a bug shared by the generator and
    the checked-in artifact cannot hide from this by agreeing with itself.
    """
    row = next(
        (line for line in sql_text.splitlines() if f"'{tool_name}'," in line),
        None,
    )
    assert row is not None, f"no seeded row for {tool_name!r} in {SQL_PATH}"
    blobs = _JSONB_BLOB.findall(row)
    assert len(blobs) == 2, (
        f"expected exactly one input_schema and one output_schema jsonb "
        f"literal on the {tool_name!r} row, found {len(blobs)}"
    )
    return json.loads(blobs[0]), json.loads(blobs[1])


def test_agent_sql_registry_projects_only_the_agent_envelope():
    """`compare_products` in the seeded SQL is `{ok, products}`, never
    `retrieval_scope_id` -- that field belongs only to the skill envelope.

    Asserts against `SQL_PATH.read_text()`, the actual generated file on disk
    that `mosaic.agent_tool_contract` is seeded from, not against
    `render_database_sql()`'s return value. The measured defect was the file
    and the generator agreeing with each other while both were wrong.
    """
    sql_text = SQL_PATH.read_text(encoding="utf-8")
    _, output_schema = _seeded_schemas(sql_text, "compare_products")

    assert set(output_schema["properties"]) == {"ok", "products"}
    assert "retrieval_scope_id" not in output_schema["properties"], (
        "retrieval_scope_id is a skill-only envelope field; it must not reach "
        "the agent registry that mosaic.agent_tool_contract audits"
    )


def test_agent_sql_registry_matches_every_contract_agent_envelope():
    """Generalizes the compare_products check across the whole seeded file.

    Every agent-surface contract's seeded output_schema properties must equal
    its payload plus exactly its own agent envelope -- never another
    surface's. Reads `load_contracts()` for the reference facts (payload and
    envelope declarations), not for the projection logic itself.
    """
    sql_text = SQL_PATH.read_text(encoding="utf-8")
    checked = 0
    for contract in tool_contracts.load_contracts():
        if "agent" not in contract["surfaces"]:
            continue
        checked += 1
        _, output_schema = _seeded_schemas(sql_text, contract["name"])
        expected = set(contract["payload_schema"]["properties"]) | set(
            contract["envelope_fields"]["agent"]
        )
        assert set(output_schema["properties"]) == expected, contract["name"]

    # Witness: the loop actually compared something, not zero contracts.
    assert checked == len(contracts_for_surface("agent"))


LIVE_HOST = "127.0.0.1"
LIVE_PORT = 8010


def _port_is_free(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        return probe.connect_ex((LIVE_HOST, port)) != 0


def _wait_until_healthy(base_url: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"{base_url} never became healthy before the deadline")


@pytest.fixture()
def live_server():
    """A real uvicorn subprocess on 8010, never 8000.

    A DBA Agent squats port 8000 on this machine, and the Vite proxy fails
    over silently to fixture data on that port, which is exactly the kind of
    green-on-broken result rule 8's corollary warns about: prove the artifact
    a real caller receives, not the loader in-process. `/api/tools` needs no
    database, so this runs with no `DATABASE_URL` and stays outside the
    `aurora` marker.
    """
    assert _port_is_free(LIVE_PORT), (
        f"port {LIVE_PORT} is already bound; free it before running this test"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "service.main:app",
            "--host",
            LIVE_HOST,
            "--port",
            str(LIVE_PORT),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
    )
    try:
        _wait_until_healthy(f"http://{LIVE_HOST}:{LIVE_PORT}", time.monotonic() + 30)
        yield f"http://{LIVE_HOST}:{LIVE_PORT}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        assert _port_is_free(LIVE_PORT), f"port {LIVE_PORT} was not released"


FORBIDDEN_ENVELOPE_FIELDS = {
    # A field that belongs only to a different surface's envelope must never
    # appear in this surface's live output_schema.
    "agent": {"retrieval_scope_id"},
    "mcp": {"ok", "retrieval_scope_id"},
    "skill": {"ok"},
}

EXPECTED_COMPARE_PRODUCTS_PROPERTIES = {
    "agent": {"ok", "products"},
    "skill": {"products", "retrieval_scope_id"},
}


def test_live_tools_endpoint_serves_only_its_own_envelope_per_surface(live_server):
    """`/api/tools?surface=X` against a live HTTP server, for all three surfaces.

    Not `TestClient`: an in-process test of the loader is not a test of the
    artifact a real caller receives (rule 8's corollary). This is the exact
    reason instance 2 of the defect went unnoticed while every in-process test
    passed -- `contracts_for_surface()` served the raw union to every surface.

    Falsifier: reverting the per-surface projection makes `compare_products`
    on `surface=agent` carry `retrieval_scope_id`, which the forbidden-field
    check below catches.
    """
    for surface in ("agent", "mcp", "skill"):
        with urllib.request.urlopen(
            f"{live_server}/api/tools?surface={surface}", timeout=5
        ) as response:
            assert response.status == 200
            payload = json.loads(response.read())

        assert payload["surface"] == surface
        # Non-emptiness witness: an empty tool list would satisfy every
        # assertion below vacuously and prove nothing about this surface.
        assert payload["tools"], f"{surface} surface returned no tools live"

        by_name = {tool["name"]: tool for tool in payload["tools"]}
        for tool in payload["tools"]:
            assert tool.get("capability"), (
                f"{tool['name']} on live surface={surface} has no capability"
            )
            leaked = (
                set(tool["output_schema"]["properties"])
                & FORBIDDEN_ENVELOPE_FIELDS[surface]
            )
            assert not leaked, (
                f"{tool['name']} on live surface={surface} output_schema "
                f"leaks {sorted(leaked)}, which belongs to a different "
                "surface's envelope"
            )

        if "compare_products" in by_name:
            properties = set(by_name["compare_products"]["output_schema"]["properties"])
            assert properties == EXPECTED_COMPARE_PRODUCTS_PROPERTIES[surface], (
                f"compare_products on live surface={surface} output_schema is "
                f"{sorted(properties)}, expected "
                f"{sorted(EXPECTED_COMPARE_PRODUCTS_PROPERTIES[surface])}"
            )


def test_growing_a_skill_only_envelope_leaves_the_agent_sql_byte_identical(
    tmp_path, monkeypatch
):
    """Cross-surface independence, with a witness that the code path ran.

    Adding a skill-only envelope field to `compare_products` must change the
    skill projection and leave the agent SQL projection byte-identical. Byte
    identity alone is not proof: it is indistinguishable from the projection
    function never having executed. A call-count witness on
    `_project_output_schema` rules that out for both surfaces under test.
    """
    calls: list[tuple[str, str]] = []
    real_projection = tool_contracts._project_output_schema

    def _witnessed(contract, surface):
        calls.append((contract["name"], surface))
        return real_projection(contract, surface)

    monkeypatch.setattr(tool_contracts, "_project_output_schema", _witnessed)

    baseline_sql = render_database_sql()

    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for contract in payload["contracts"]:
        if contract["name"] == "compare_products":
            contract["envelope_fields"]["skill"].append("trace_id")
            contract["output_schema"]["properties"]["trace_id"] = {
                "type": ["string", "null"]
            }

    changed = tmp_path / "skill-only-envelope-growth.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(tool_contracts, "CONTRACT_PATH", changed)

    calls.clear()
    skill_contracts = contracts_for_surface("skill")
    agent_sql = render_database_sql()

    # Witness: the per-surface projection actually executed for compare_
    # products on both surfaces under test, not just for "skill" while
    # "agent" happened to look unaffected because nothing ran.
    assert ("compare_products", "skill") in calls
    assert ("compare_products", "agent") in calls

    by_name = {contract["name"]: contract for contract in skill_contracts}
    assert "trace_id" in by_name["compare_products"]["output_schema"]["properties"], (
        "the skill projection did not pick up its own new envelope field"
    )

    assert agent_sql == baseline_sql, (
        "growing compare_products's skill-only envelope changed the agent SQL "
        "registry projection, which must not depend on any other surface"
    )
