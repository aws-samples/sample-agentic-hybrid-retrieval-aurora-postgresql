import ast
import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.tool_contracts import (
    SQL_PATH,
    contracts_for_surface,
    render_database_sql,
    shared_contract_receipt,
)
from service import agent_tools
from service.main import app

ROOT = Path(__file__).resolve().parents[1]


def _schema_arguments(surface: str) -> dict[str, set[str]]:
    return {
        contract["name"]: set(contract["input_schema"]["properties"])
        for contract in contracts_for_surface(surface)
    }


def _required_arguments(surface: str) -> dict[str, set[str]]:
    return {
        contract["name"]: set(contract["input_schema"].get("required", []))
        for contract in contracts_for_surface(surface)
    }


def _function_arguments(path: Path, names: set[str]) -> dict[str, set[str]]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: {argument.arg for argument in node.args.args}
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }


def test_database_registry_is_generated_from_the_canonical_contract():
    assert SQL_PATH.read_text(encoding="utf-8") == render_database_sql()


def test_shared_agent_and_mcp_tools_preserve_portable_output_invariants():
    assert shared_contract_receipt() == {
        "shared_tools": ["get_product_evidence", "search_products"],
        "preserved_fields": ["tool_version", "output_schema", "read_only"],
        "transport_specific_fields": ["input_schema", "transport_trace"],
    }


def test_strands_signatures_match_the_agent_contract():
    expected = _schema_arguments("agent")
    required = _required_arguments("agent")
    functions = {
        tool.tool_name: tool.__wrapped__ for tool in agent_tools.TOOL_FUNCTIONS
    }

    assert set(functions) == set(expected)
    for name, function in functions.items():
        signature = inspect.signature(function)
        assert set(signature.parameters) == expected[name]
        assert {
            argument
            for argument, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
        } == required[name]


def test_mcp_signatures_match_the_mcp_contract():
    expected = _schema_arguments("mcp")
    functions = _function_arguments(
        ROOT / "mcp-server" / "catalog_mcp" / "server.py",
        set(expected),
    )

    assert functions == expected


def test_api_exposes_explicit_agent_and_mcp_subsets():
    client = TestClient(app)

    agent = client.get("/api/tools").json()
    mcp = client.get("/api/tools", params={"surface": "mcp"}).json()

    assert agent["surface"] == "agent"
    assert {tool["name"] for tool in agent["tools"]} == set(_schema_arguments("agent"))
    assert mcp["surface"] == "mcp"
    assert {tool["name"] for tool in mcp["tools"]} == set(_schema_arguments("mcp"))
    assert all(tool["read_only"] for tool in agent["tools"] + mcp["tools"])
