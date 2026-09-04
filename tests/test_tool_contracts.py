import ast
import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.tool_contracts import (
    SQL_PATH,
    capability_parity_receipt,
    contracts_for_surface,
    render_database_sql,
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


def test_shared_capabilities_preserve_portable_semantic_invariants():
    """Grouped by capability, so two wire names for one capability are compared.

    The previous version of this test grouped by name and reported
    `explain_retrieval` and `inspect_retrieval_run` as unrelated, which is how
    their output schemas drifted unobserved.
    """
    assert capability_parity_receipt() == {
        "shared_capabilities": [
            "compare_products",
            "explain_retrieval",
            "get_product_evidence",
            "open_retrieval",
        ],
        "cross_contract_capabilities": ["explain_retrieval"],
        "capabilities": [
            "compare_products",
            "explain_retrieval",
            "get_product_evidence",
            "open_retrieval",
            "synthesize_cited_answer",
        ],
        "preserved_fields": ["tool_version", "read_only", "payload_schema"],
        "transport_specific_fields": [
            "name",
            "input_schema",
            "envelope_fields",
            "transport_trace",
        ],
        "union_checks_performed": 6,
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


def test_agent_bounds_match_runtime_constants():
    """Declared JSON-Schema bounds must equal the runtime bounds they mirror.

    `test_strands_signatures_match_the_agent_contract` above only compares
    parameter *name* sets, so a schema that named `product_ids` correctly but
    bounded it to the wrong count would pass it forever. This pins each bound
    against `service.agent_tools`'s module constants: a source independent of
    the JSON file being checked, not a `len()` of anything the JSON declares.
    """
    contracts = {
        contract["name"]: contract for contract in contracts_for_surface("agent")
    }

    compare_ids = contracts["compare_products"]["input_schema"]["properties"][
        "product_ids"
    ]
    assert (
        compare_ids["minItems"],
        compare_ids["maxItems"],
    ) == agent_tools.COMPARE_PRODUCT_COUNT

    synthesis_ids = contracts["synthesize_cited_answer"]["input_schema"]["properties"][
        "product_ids"
    ]
    assert (
        synthesis_ids["minItems"],
        synthesis_ids["maxItems"],
    ) == agent_tools.SYNTHESIS_PRODUCT_COUNT

    search_query = contracts["search_products"]["input_schema"]["properties"]["query"]
    assert search_query["minLength"] == agent_tools.SEARCH_QUERY_MIN_LENGTH


def test_mcp_signatures_match_the_mcp_contract():
    expected = _schema_arguments("mcp")
    functions = _function_arguments(
        ROOT / "mcp-server" / "catalog_mcp" / "server.py",
        set(expected),
    )

    assert functions == expected


def test_api_exposes_explicit_agent_mcp_and_skill_subsets():
    client = TestClient(app)

    for surface in ("agent", "mcp", "skill"):
        payload = client.get("/api/tools", params={"surface": surface}).json()
        assert payload["surface"] == surface
        # Non-emptiness witness: an empty tool list would satisfy the set
        # equality below vacuously, proving nothing about this surface.
        assert payload["tools"], f"{surface} surface returned no tools"
        assert {tool["name"] for tool in payload["tools"]} == set(
            _schema_arguments(surface)
        )
        assert all(tool["read_only"] for tool in payload["tools"])
