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
SKILL_PATH = ROOT / "skills" / "mosaic-hybrid-retrieval" / "SKILL.md"
SKILL_BEGIN = "<!-- BEGIN GENERATED CONTRACT: scripts/tool_contracts.py -->\n"
SKILL_END = "<!-- END GENERATED CONTRACT -->"
Surface = Literal["agent", "mcp", "skill"]

#: The route each skill capability is served on. Declared here rather than in the
#: registry because a route is a property of this deployment, not of the
#: capability, and the contract is meant to outlive one HTTP layout. A test
#: asserts every one of these is registered on the app.
SKILL_ROUTES = {
    "search_products": "POST /api/search",
    "get_product_evidence": "POST /api/products/{product_id}/evidence",
    "compare_products": "POST /api/retrieval/events/{search_event_id}/compare",
    "explain_retrieval": "GET /api/retrieval/events/{search_event_id}",
}


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
        capability = contract.get("capability")
        if not isinstance(capability, str) or not capability:
            raise ToolContractError(
                f"agent tool contract {name!r} has capability={capability!r}; "
                "declare the semantic capability it implements"
            )
        payload_schema = contract.get("payload_schema")
        if not isinstance(payload_schema, dict):
            raise ToolContractError(
                f"agent tool contract {name!r} has payload_schema="
                f"{payload_schema!r}; declare the transport-independent "
                "semantic payload as an object"
            )
        envelopes = contract.get("envelope_fields")
        if not isinstance(envelopes, dict) or set(envelopes) != set(surfaces):
            raise ToolContractError(
                f"agent tool contract {name!r} declares envelope_fields for "
                f"{sorted(envelopes or {})} but surfaces {sorted(surfaces)}; "
                "declare one envelope list per surface, empty when there is none"
            )
    return contracts


def _project_output_schema(
    contract: dict[str, Any], surface: Surface
) -> dict[str, Any]:
    """Payload plus only the envelope fields this one surface declares.

    `contract["output_schema"]` is the canonical union across every surface's
    envelope, which is correct for cross-surface introspection but wrong the
    moment it is copied verbatim into an artifact that claims to speak for one
    surface (house-standards.md rule 8). Project at the boundary instead:
    every returned property must come from the transport-independent payload
    or from this surface's own envelope, never another surface's.
    """
    payload_properties = contract["payload_schema"]["properties"]
    canonical_properties = contract["output_schema"]["properties"]
    envelope_fields = contract["envelope_fields"][surface]
    properties = {
        **payload_properties,
        **{field: canonical_properties[field] for field in envelope_fields},
    }
    required = [
        field
        for field in contract["output_schema"].get("required", [])
        if field in properties
    ]
    return {
        "type": contract["output_schema"]["type"],
        "required": required,
        "properties": properties,
    }


def contracts_for_surface(surface: Surface) -> list[dict[str, Any]]:
    """Return public contracts with the selected surface schema resolved."""
    return [
        {
            "name": contract["name"],
            "capability": contract["capability"],
            "tool_version": contract["tool_version"],
            "description": contract["description"],
            "input_schema": contract["input_schemas"][surface],
            "output_schema": _project_output_schema(contract, surface),
            "read_only": contract["read_only"],
        }
        for contract in load_contracts()
        if surface in contract["surfaces"]
    ]


def capability_parity_receipt() -> dict[str, Any]:
    """Prove one capability means the same thing on every surface it appears on.

    Grouped by `capability`, not by wire name. The previous receipt keyed on name
    and therefore reported `explain_retrieval` and `inspect_retrieval_run` as
    unrelated, which let their output schemas drift unobserved. A transport may
    wrap the payload in its own envelope, but only in the fields it declared.
    """
    by_capability: dict[str, list[dict[str, Any]]] = {}
    for contract in load_contracts():
        by_capability.setdefault(contract["capability"], []).append(contract)

    preserved = ("tool_version", "read_only", "payload_schema")
    mismatches: dict[str, list[str]] = {}
    for capability, contracts in by_capability.items():
        first = contracts[0]
        drifted = sorted(
            {
                field
                for other in contracts[1:]
                for field in preserved
                if other[field] != first[field]
            }
        )
        if drifted:
            mismatches[capability] = drifted
    if mismatches:
        raise ToolContractError(
            "one capability disagrees with itself across surfaces; fix "
            f"db/config/agent_tool_contracts.json: {mismatches}"
        )

    # Counts every contract this loop actually compares. If the loop is deleted
    # or short-circuited, this stays 0 and the receipt says so -- a PASS with no
    # exception raised is otherwise indistinguishable from the loop not running.
    union_checks_performed = 0
    for contract in load_contracts():
        union_checks_performed += 1
        payload = set(contract["payload_schema"]["properties"])
        envelopes = {
            field
            for surface in contract["surfaces"]
            for field in contract["envelope_fields"][surface]
        }
        declared = set(contract["output_schema"]["properties"])
        if declared != payload | envelopes:
            raise ToolContractError(
                f"agent tool contract {contract['name']!r} declares output "
                f"properties {sorted(declared)}; found payload plus every "
                f"declared envelope {sorted(payload | envelopes)}; fix: change "
                "output_schema, payload_schema, or envelope_fields so the "
                "three agree"
            )

    return {
        # Two distinct facts, deliberately not one field. A capability declared
        # once with several surfaces IS shared across surfaces; it simply needs no
        # cross-contract comparison, because its invariants are declared exactly
        # once and cannot disagree with themselves.
        "shared_capabilities": sorted(
            capability
            for capability, contracts in by_capability.items()
            if len({surface for c in contracts for surface in c["surfaces"]}) > 1
        ),
        # Only these require the parity comparison.
        "cross_contract_capabilities": sorted(
            capability
            for capability, contracts in by_capability.items()
            if len(contracts) > 1
        ),
        "capabilities": sorted(by_capability),
        "preserved_fields": list(preserved),
        "transport_specific_fields": [
            "name",
            "input_schema",
            "envelope_fields",
            "transport_trace",
        ],
        "union_checks_performed": union_checks_performed,
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


def render_skill_contract() -> str:
    """Render the skill operations table from the canonical registry."""
    lines = [
        "",
        "| Operation | Capability | Route | Required arguments | Read-only |",
        "|---|---|---|---|---|",
    ]
    for contract in contracts_for_surface("skill"):
        name = contract["name"]
        required = contract["input_schema"].get("required", [])
        lines.append(
            f"| `{name}` | `{contract['capability']}` | "
            f"`{SKILL_ROUTES[name]}` | "
            f"{', '.join(f'`{item}`' for item in required)} | "
            f"{'yes' if contract['read_only'] else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = render_database_sql()
    skill_block = render_skill_contract()
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    start = skill_text.index(SKILL_BEGIN) + len(SKILL_BEGIN)
    end = skill_text.index(SKILL_END)
    if args.write:
        SQL_PATH.write_text(rendered, encoding="utf-8")
        SKILL_PATH.write_text(
            skill_text[:start] + skill_block + skill_text[end:],
            encoding="utf-8",
        )
        print(f"Wrote {SQL_PATH.relative_to(ROOT)} and {SKILL_PATH.relative_to(ROOT)}")
        return 0
    if SQL_PATH.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            "agent tool SQL registry differs from "
            "db/config/agent_tool_contracts.json; run "
            "python scripts/tool_contracts.py --write"
        )
    if skill_text[start:end] != skill_block:
        raise SystemExit(
            "SKILL.md's generated contract block differs from "
            "db/config/agent_tool_contracts.json; run "
            "python scripts/tool_contracts.py --write"
        )
    receipt = capability_parity_receipt()
    print(
        f"PASS: canonical registry projects "
        f"{len(contracts_for_surface('agent'))} agent, "
        f"{len(contracts_for_surface('mcp'))} MCP, and "
        f"{len(contracts_for_surface('skill'))} skill contracts; "
        f"{len(receipt['shared_capabilities'])} capabilities preserve version, "
        f"semantic payload, and read-only policy across surfaces; SQL registry "
        f"and SKILL.md match the source of truth"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
