#!/usr/bin/env python3
"""Load agent-tool contracts and render the database registry from one source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "db" / "config" / "agent_tool_contracts.json"
SQL_PATH = ROOT / "db" / "sql" / "16_seed_tool_contracts.sql"
Surface = Literal["agent", "mcp"]


class ToolContractError(RuntimeError):
    """The canonical tool contract is internally inconsistent."""


def load_contracts() -> list[dict[str, Any]]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ToolContractError(
            f"agent tool contract version is {payload.get('version')!r}; "
            "fix db/config/agent_tool_contracts.json to use version 1"
        )
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ToolContractError(
            "agent tool contracts are empty; add at least one contract"
        )
    names: set[str] = set()
    for contract in contracts:
        name = contract.get("name")
        if not isinstance(name, str) or not name:
            raise ToolContractError(
                f"agent tool contract name is {name!r}; use a non-empty string"
            )
        if name in names:
            raise ToolContractError(
                f"agent tool contract {name!r} is duplicated; keep one declaration"
            )
        names.add(name)
        surfaces = contract.get("surfaces")
        schemas = contract.get("input_schemas")
        if not isinstance(surfaces, list) or not surfaces:
            raise ToolContractError(
                f"agent tool contract {name!r} has surfaces={surfaces!r}; "
                "declare agent, mcp, or both"
            )
        if not isinstance(schemas, dict):
            raise ToolContractError(
                f"agent tool contract {name!r} has no input_schemas object"
            )
        missing = sorted(set(surfaces) - set(schemas))
        extra = sorted(set(schemas) - set(surfaces))
        if missing or extra:
            raise ToolContractError(
                f"agent tool contract {name!r} has missing schemas={missing} "
                f"and undeclared schemas={extra}; make surfaces and schemas agree"
            )
    return contracts


def contracts_for_surface(surface: Surface) -> list[dict[str, Any]]:
    """Return public contracts with the selected surface schema resolved."""
    return [
        {
            "name": contract["name"],
            "tool_version": contract["tool_version"],
            "description": contract["description"],
            "input_schema": contract["input_schemas"][surface],
            "output_schema": contract["output_schema"],
            "read_only": contract["read_only"],
        }
        for contract in load_contracts()
        if surface in contract["surfaces"]
    ]


def shared_contract_receipt() -> dict[str, Any]:
    """Describe the invariants preserved across agent and MCP projections."""
    by_surface = {
        surface: {
            contract["name"]: contract for contract in contracts_for_surface(surface)
        }
        for surface in ("agent", "mcp")
    }
    shared_names = sorted(set(by_surface["agent"]) & set(by_surface["mcp"]))
    preserved = ("tool_version", "output_schema", "read_only")
    mismatches = {
        name: [
            field
            for field in preserved
            if by_surface["agent"][name][field] != by_surface["mcp"][name][field]
        ]
        for name in shared_names
    }
    mismatches = {name: fields for name, fields in mismatches.items() if fields}
    if mismatches:
        raise ToolContractError(
            "shared agent and MCP tool invariants drifted; "
            f"fix db/config/agent_tool_contracts.json: {mismatches}"
        )
    return {
        "shared_tools": shared_names,
        "preserved_fields": list(preserved),
        "transport_specific_fields": ["input_schema", "transport_trace"],
    }


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_database_sql() -> str:
    """Render only the bounded agent contracts persisted with agent receipts."""
    rows = []
    for contract in contracts_for_surface("agent"):
        rows.append(
            "    ("
            + ", ".join(
                (
                    _sql_literal(contract["name"]),
                    _sql_literal(contract["tool_version"]),
                    _sql_literal(contract["description"]),
                    _sql_literal(
                        json.dumps(
                            contract["input_schema"],
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
                    + "::jsonb",
                    _sql_literal(
                        json.dumps(
                            contract["output_schema"],
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
                    + "::jsonb",
                    "true" if contract["read_only"] else "false",
                )
            )
            + ")"
        )
    values = ",\n".join(rows)
    return f"""\\set ON_ERROR_STOP on
-- Generated by scripts/tool_contracts.py from
-- db/config/agent_tool_contracts.json. Do not edit this file by hand.

UPDATE mosaic.agent_tool_contract
SET enabled = false
WHERE tool_name IN ('search_catalog', 'explain_recommendation');

INSERT INTO mosaic.agent_tool_contract (
    tool_name, tool_version, description, input_schema, output_schema, read_only
)
VALUES
{values}
ON CONFLICT (tool_name, tool_version) DO UPDATE
SET description = EXCLUDED.description,
    input_schema = EXCLUDED.input_schema,
    output_schema = EXCLUDED.output_schema,
    read_only = EXCLUDED.read_only,
    enabled = true;
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = render_database_sql()
    if args.write:
        SQL_PATH.write_text(rendered, encoding="utf-8")
        print(f"Wrote {SQL_PATH.relative_to(ROOT)}")
        return 0
    current = SQL_PATH.read_text(encoding="utf-8")
    if current != rendered:
        raise SystemExit(
            "agent tool SQL registry differs from "
            "db/config/agent_tool_contracts.json; run "
            "python scripts/tool_contracts.py --write"
        )
    receipt = shared_contract_receipt()
    print(
        f"PASS: canonical registry projects "
        f"{len(contracts_for_surface('agent'))} agent and "
        f"{len(contracts_for_surface('mcp'))} MCP contracts; "
        f"{len(receipt['shared_tools'])} shared tools preserve version, output "
        f"schema, and read-only policy; SQL registry matches all agent tools"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
