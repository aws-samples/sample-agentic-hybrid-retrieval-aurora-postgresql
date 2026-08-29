#!/usr/bin/env python3
"""Load agent-tool contracts and render the database registry from one source."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal, get_args

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONTRACT_PATH = ROOT / "db" / "config" / "agent_tool_contracts.json"
SQL_PATH = ROOT / "db" / "sql" / "16_seed_tool_contracts.sql"
SKILL_PATH = ROOT / "skills" / "mosaic-hybrid-retrieval" / "SKILL.md"
SKILL_HTTP_REFERENCE_PATH = (
    ROOT / "skills" / "mosaic-hybrid-retrieval" / "references" / "http-api.md"
)
SKILL_BEGIN = "<!-- BEGIN GENERATED CONTRACT: scripts/tool_contracts.py -->\n"
SKILL_END = "<!-- END GENERATED CONTRACT -->"
Surface = Literal["agent", "mcp", "skill"]

#: How the transport-independent skill arguments bind to this deployment's HTTP
#: API. Keys inside path/query/body are skill argument names; values are wire
#: destinations. Dotted body destinations are nested JSON paths.
#:
#: This is deliberately outside `agent_tool_contracts.json`: routes and JSON
#: layout belong to one adapter, while the canonical capability contract must
#: survive adapter changes. `validate_skill_http_bindings` makes this seam
#: exhaustive in both directions.
SKILL_HTTP_BINDINGS: dict[str, dict[str, Any]] = {
    "search_products": {
        "method": "POST",
        "route": "/api/search",
        "path": {},
        "query": {},
        "body": {
            "query": "query",
            "domain": "filters.domain",
            "category_key": "filters.category_key",
            "brand": "filters.brand",
            "availability": "filters.availability",
            "in_stock_only": "filters.in_stock_only",
            "min_price_cents": "filters.min_price_cents",
            "max_price_cents": "filters.max_price_cents",
            "min_rating": "filters.min_rating",
            "attributes": "filters.attributes",
            "limit": "limit",
            "authorized_limit": "authorized_limit",
            "include_diagnostics": "include_diagnostics",
            "rerank": "rerank",
        },
    },
    "get_product_evidence": {
        "method": "POST",
        "route": "/api/products/{product_id}/evidence",
        "path": {"product_id": "product_id"},
        "query": {},
        "body": {
            "retrieval_scope_id": "retrieval_scope_id",
            "evidence_query": "evidence_query",
            "limit": "limit",
        },
    },
    "compare_products": {
        "method": "POST",
        "route": "/api/retrieval/events/{search_event_id}/compare",
        "path": {"retrieval_scope_id": "search_event_id"},
        "query": {},
        "body": {"product_ids": "product_ids"},
    },
    "explain_retrieval": {
        "method": "GET",
        "route": "/api/retrieval/events/{search_event_id}",
        "path": {"retrieval_scope_id": "search_event_id"},
        "query": {},
        "body": {},
    },
}

SKILL_ROUTES = {
    name: f"{binding['method']} {binding['route']}"
    for name, binding in SKILL_HTTP_BINDINGS.items()
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
        route = SKILL_ROUTES.get(name)
        if route is None:
            raise ToolContractError(
                f"SKILL_ROUTES has no entry for skill contract {name!r}: "
                f"found routes for {sorted(SKILL_ROUTES)}; "
                f"fix: add SKILL_ROUTES[{name!r}] = '<METHOD> <path>' in "
                "scripts/tool_contracts.py"
            )
        required = contract["input_schema"].get("required", [])
        lines.append(
            f"| `{name}` | `{contract['capability']}` | "
            f"`{route}` | "
            f"{', '.join(f'`{item}`' for item in required)} | "
            f"{'yes' if contract['read_only'] else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


def validate_skill_http_bindings(
    *,
    bindings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Prove every skill argument has exactly one executable HTTP destination."""
    selected = bindings if bindings is not None else SKILL_HTTP_BINDINGS
    contracts = {
        contract["name"]: contract for contract in contracts_for_surface("skill")
    }
    missing_operations = sorted(set(contracts) - set(selected))
    extra_operations = sorted(set(selected) - set(contracts))
    if missing_operations or extra_operations:
        raise ToolContractError(
            "skill HTTP bindings do not cover the skill surface exactly: "
            f"missing operations={missing_operations}, "
            f"extra operations={extra_operations}; fix: add or remove entries "
            "in SKILL_HTTP_BINDINGS until they match the skill contracts"
        )

    # Import lazily: service.main imports contracts_for_surface from this module.
    # Validation runs only after module initialization, which keeps the service's
    # normal import path acyclic while still checking the real FastAPI boundary.
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    from service.main import app

    def nested_model(annotation: Any) -> type[BaseModel] | None:
        candidates = (annotation, *get_args(annotation))
        for candidate in candidates:
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                return candidate
        return None

    mapped_arguments = 0
    for name, contract in contracts.items():
        binding = selected[name]
        method = binding.get("method")
        route = binding.get("route")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ToolContractError(
                f"skill HTTP binding {name!r} has method={method!r}; "
                "fix: use an uppercase HTTP method"
            )
        if not isinstance(route, str) or not route.startswith("/"):
            raise ToolContractError(
                f"skill HTTP binding {name!r} has route={route!r}; "
                "fix: use an absolute API path beginning with /"
            )

        locations: dict[str, str] = {}
        duplicates: set[str] = set()
        for location in ("path", "query", "body"):
            mapping = binding.get(location)
            if not isinstance(mapping, dict):
                raise ToolContractError(
                    f"skill HTTP binding {name!r} has {location}={mapping!r}; "
                    "fix: declare an argument-to-destination object, empty "
                    "when this route uses none"
                )
            for argument, destination in mapping.items():
                if argument in locations:
                    duplicates.add(argument)
                locations[argument] = location
                if not isinstance(destination, str) or not destination:
                    raise ToolContractError(
                        f"skill HTTP binding {name!r} maps {argument!r} to "
                        f"{destination!r}; fix: use a non-empty wire destination"
                    )

        placeholders = set(re.findall(r"{([^{}]+)}", route))
        path_destinations = set(binding["path"].values())
        missing_placeholders = sorted(placeholders - path_destinations)
        extra_path_destinations = sorted(path_destinations - placeholders)
        if missing_placeholders or extra_path_destinations:
            raise ToolContractError(
                f"skill HTTP binding {name!r} route {route!r} has placeholders "
                f"{sorted(placeholders)} but path destinations "
                f"{sorted(path_destinations)}; missing placeholders="
                f"{missing_placeholders}, extra path destinations="
                f"{extra_path_destinations}; fix: map each route placeholder "
                "from exactly one skill argument"
            )

        registered = [
            candidate
            for candidate in app.routes
            if isinstance(candidate, APIRoute)
            and candidate.path == route
            and method in candidate.methods
        ]
        if len(registered) != 1:
            raise ToolContractError(
                f"skill HTTP binding {name!r} resolves to {len(registered)} "
                f"registered routes for {method} {route}; fix: use exactly one "
                "method and path served by service.main.app"
            )
        api_route = registered[0]

        query_parameters = {
            parameter.alias for parameter in api_route.dependant.query_params
        }
        unknown_query_destinations = sorted(
            set(binding["query"].values()) - query_parameters
        )
        if unknown_query_destinations:
            raise ToolContractError(
                f"skill HTTP binding {name!r} maps query destinations "
                f"{unknown_query_destinations}, but {method} {route} accepts "
                f"{sorted(query_parameters)}; fix: use a registered query "
                "parameter or move the argument to its real location"
            )

        body_model = (
            nested_model(api_route.body_field.field_info.annotation)
            if api_route.body_field is not None
            else None
        )
        for argument, destination in binding["body"].items():
            if destination.rsplit(".", 1)[-1] != argument:
                raise ToolContractError(
                    f"skill HTTP binding {name!r} maps body argument "
                    f"{argument!r} to {destination!r}; fix: keep the wire leaf "
                    f"named {argument!r} and use only parent objects for nesting"
                )
            current_model = body_model
            for segment in destination.split("."):
                if current_model is None or segment not in current_model.model_fields:
                    model_name = (
                        current_model.__name__
                        if current_model is not None
                        else "no request body"
                    )
                    raise ToolContractError(
                        f"skill HTTP binding {name!r} maps {argument!r} to body "
                        f"destination {destination!r}, but segment {segment!r} "
                        f"is absent from {model_name} on {method} {route}; "
                        "fix: map the argument to a field the registered "
                        "Pydantic request model accepts"
                    )
                field = current_model.model_fields[segment]
                current_model = nested_model(field.annotation)

        declared = set(contract["input_schema"]["properties"])
        mapped = set(locations)
        missing_arguments = sorted(declared - mapped)
        extra_arguments = sorted(mapped - declared)
        if missing_arguments or extra_arguments or duplicates:
            raise ToolContractError(
                f"skill HTTP binding {name!r} has missing arguments="
                f"{missing_arguments}, extra arguments={extra_arguments}, "
                f"duplicate arguments={sorted(duplicates)}; fix: map every "
                "declared skill argument exactly once across path, query, or body"
            )

        mapped_arguments += len(mapped)

    return {
        "operations": len(contracts),
        "mapped_arguments": mapped_arguments,
    }


def render_skill_http_reference() -> str:
    """Render the checked HTTP adapter map inside the takeaway package."""
    validate_skill_http_bindings()
    lines = [
        "# HTTP adapter map",
        "",
        "<!-- Generated by scripts/tool_contracts.py. Do not edit by hand. -->",
        "",
        "The skill contract uses transport-independent argument names. This file",
        "shows exactly where this deployment sends each one over HTTP. A dotted",
        "JSON destination is nested, so `filters.domain` means",
        '`{"filters": {"domain": ...}}`.',
        "",
    ]
    contracts = {
        contract["name"]: contract for contract in contracts_for_surface("skill")
    }
    for name, binding in SKILL_HTTP_BINDINGS.items():
        lines.extend(
            [
                f"## `{name}`",
                "",
                f"`{binding['method']} {binding['route']}`",
                "",
                "| Skill argument | HTTP location | Required |",
                "|---|---|---|",
            ]
        )
        required = set(contracts[name]["input_schema"].get("required", []))
        for location in ("path", "query", "body"):
            for argument, destination in binding[location].items():
                if location == "path":
                    wire_location = f"path `{{{destination}}}`"
                elif location == "query":
                    wire_location = f"query `{destination}`"
                else:
                    wire_location = f"JSON body `{destination}`"
                lines.append(
                    f"| `{argument}` | {wire_location} | "
                    f"{'yes' if argument in required else 'no'} |"
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
    http_reference = render_skill_http_reference()
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    start = skill_text.index(SKILL_BEGIN) + len(SKILL_BEGIN)
    end = skill_text.index(SKILL_END)
    if args.write:
        SQL_PATH.write_text(rendered, encoding="utf-8")
        SKILL_PATH.write_text(
            skill_text[:start] + skill_block + skill_text[end:],
            encoding="utf-8",
        )
        SKILL_HTTP_REFERENCE_PATH.write_text(http_reference, encoding="utf-8")
        print(
            f"Wrote {SQL_PATH.relative_to(ROOT)}, "
            f"{SKILL_PATH.relative_to(ROOT)}, and "
            f"{SKILL_HTTP_REFERENCE_PATH.relative_to(ROOT)}"
        )
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
    if SKILL_HTTP_REFERENCE_PATH.read_text(encoding="utf-8") != http_reference:
        raise SystemExit(
            "skill HTTP reference differs from SKILL_HTTP_BINDINGS; run "
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
        f"SKILL.md and the HTTP adapter map match the source of truth"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
