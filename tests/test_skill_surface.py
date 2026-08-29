"""Capability-keyed contract parity across surfaces."""

import ast
import copy
import json
import re
import typing
from pathlib import Path

import pytest

from scripts import tool_contracts
from scripts.tool_contracts import (
    CONTRACT_PATH,
    SKILL_HTTP_REFERENCE_PATH,
    SKILL_PATH,
    ToolContractError,
    capability_parity_receipt,
    contracts_for_surface,
    load_contracts,
    render_skill_http_reference,
    validate_skill_http_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_PATH = (
    ROOT / "skills" / "mosaic-hybrid-retrieval" / "references" / "composition.md"
)
ADAPTATION_PATH = (
    ROOT / "skills" / "mosaic-hybrid-retrieval" / "references" / "adapting.md"
)


def test_every_contract_declares_a_capability(tmp_path, monkeypatch):
    """Exercise `load_contracts`'s own capability guard directly.

    The previous version called `load_contracts()` un-mutated and then asserted
    every contract's `capability` was truthy. `load_contracts` already raises
    before returning if any contract lacks a capability, so that assertion was
    unreachable: it could never fail via its own logic, only via the loader's.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    del payload["contracts"][0]["capability"]

    dropped = tmp_path / "missing-capability.json"
    dropped.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", dropped)

    with pytest.raises(ToolContractError, match="capability"):
        load_contracts()


def test_explain_is_one_capability_under_two_wire_names():
    by_name = {contract["name"]: contract for contract in load_contracts()}

    assert by_name["explain_retrieval"]["capability"] == "explain_retrieval"
    assert by_name["inspect_retrieval_run"]["capability"] == "explain_retrieval"
    assert by_name["search_products"]["capability"] == "open_retrieval"


def test_shared_capabilities_agree_on_their_semantic_payload():
    """`explain_retrieval` needs the parity comparison; the others do not.

    `shared_capabilities` and `cross_contract_capabilities` answer different
    questions. `get_product_evidence` and `open_retrieval` are each declared
    once but exposed on two surfaces, so they are shared across surfaces
    without needing cross-contract comparison: their invariants are declared
    exactly once and cannot disagree with themselves. `explain_retrieval` is
    declared under two separate contract records (`explain_retrieval` and
    `inspect_retrieval_run`), so it is the only capability where the parity
    comparison in `capability_parity_receipt` actually runs.
    """
    receipt = capability_parity_receipt()

    assert receipt["cross_contract_capabilities"] == ["explain_retrieval"]
    assert {"get_product_evidence", "open_retrieval"} <= set(
        receipt["shared_capabilities"]
    )
    assert receipt["preserved_fields"] == [
        "tool_version",
        "read_only",
        "payload_schema",
    ]


def test_output_schema_is_exactly_payload_plus_every_declared_envelope():
    """`output_schema` is per-contract while envelopes are per-surface.

    So it is the union across surfaces, not a per-surface shape. Asserting exact
    equality against that union is what keeps an undeclared key from appearing in
    `output_schema` without also appearing in a payload or an envelope.
    """
    for contract in load_contracts():
        payload = set(contract["payload_schema"]["properties"])
        envelopes = {
            field
            for surface in contract["surfaces"]
            for field in contract["envelope_fields"][surface]
        }
        declared = set(contract["output_schema"]["properties"])
        assert declared == payload | envelopes, (
            f"{contract['name']}: output_schema is {sorted(declared)} but "
            f"payload plus all declared envelopes is "
            f"{sorted(payload | envelopes)}"
        )


def test_union_rule_accepts_the_unmodified_contract_set():
    """Baseline PASS, against the real production validator.

    Calls `capability_parity_receipt()` itself, unlike
    `test_output_schema_is_exactly_payload_plus_every_declared_envelope` above,
    which re-derives the same set comparison against `load_contracts()` and
    would keep passing even if the union loop inside
    `capability_parity_receipt` were deleted entirely. The witness assertion
    below is what tells a PASS here apart from that loop never having run.
    """
    receipt = capability_parity_receipt()

    assert receipt["union_checks_performed"] == len(load_contracts())


def test_union_rule_rejects_an_undeclared_output_field(tmp_path, monkeypatch):
    """Permanent falsifier for the envelope-union rule, failure direction one.

    Deleting the union loop in `capability_parity_receipt`
    (scripts/tool_contracts.py) would not fail a single other test in this
    suite: the baseline test above calls the real function but never mutates
    anything that would make a deleted loop visible, and
    `test_payload_drift_between_surfaces_is_caught` below mutates a field the
    earlier cross-contract check catches first. This adds an extra, undeclared
    field to `compare_products`'s `output_schema` -- a single-contract
    capability, so the cross-contract check structurally cannot fire and mask
    which branch raised.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for contract in payload["contracts"]:
        if contract["name"] == "compare_products":
            contract["output_schema"]["properties"]["extra_untracked_field"] = {
                "type": "string"
            }

    drifted = tmp_path / "union-extra-field.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", drifted)

    with pytest.raises(ToolContractError, match="declares output properties"):
        capability_parity_receipt()


def test_union_rule_rejects_a_missing_required_payload_field(tmp_path, monkeypatch):
    """Permanent falsifier for the envelope-union rule, failure direction two.

    The paired failure direction to the test above: omit a payload field from
    `output_schema` instead of adding an untracked one. `declared != payload |
    envelopes` can fail from either side of that inequality; a battery that
    only ever adds an extra field never proves the "missing" side is checked.
    Same single-contract capability, for the same structural reason.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for contract in payload["contracts"]:
        if contract["name"] == "compare_products":
            del contract["output_schema"]["properties"]["products"]

    drifted = tmp_path / "union-missing-field.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", drifted)

    with pytest.raises(ToolContractError, match="declares output properties"):
        capability_parity_receipt()


def test_union_rule_accepts_a_permitted_envelope_only_change(tmp_path, monkeypatch):
    """Independence half of the envelope-union battery.

    Growing a contract's own envelope, and updating that same contract's
    `output_schema` to match, must not raise. `compare_products` is a
    single-contract capability, so a PASS here proves the union rule itself is
    satisfied, not that the earlier cross-contract check simply never ran.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for contract in payload["contracts"]:
        if contract["name"] == "compare_products":
            contract["envelope_fields"]["agent"].append("trace_id")
            contract["output_schema"]["properties"]["trace_id"] = {
                "type": ["string", "null"]
            }

    changed = tmp_path / "union-envelope-only.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", changed)

    receipt = capability_parity_receipt()

    assert receipt["union_checks_performed"] == len(load_contracts())


def test_payload_drift_between_surfaces_is_caught(tmp_path, monkeypatch):
    """Permanent falsifier: reintroduce the run/search_event drift.

    This is the exact divergence the name-keyed receipt could not see. If this
    test ever passes without raising, the gate has gone blind again.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for contract in payload["contracts"]:
        if contract["name"] == "explain_retrieval":
            properties = contract["payload_schema"]["properties"]
            properties["search_event"] = properties.pop("run")
            contract["output_schema"]["properties"]["search_event"] = contract[
                "output_schema"
            ]["properties"].pop("run")
            contract["payload_schema"]["required"] = ["search_event", "candidates"]
            contract["output_schema"]["required"] = [
                "ok",
                "search_event",
                "candidates",
            ]

    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", drifted)

    with pytest.raises(ToolContractError, match="disagrees with itself"):
        capability_parity_receipt()


def test_explain_retrieval_envelope_change_is_independent_across_its_two_contracts(
    tmp_path, monkeypatch
):
    """Formalizes the manual envelope-independence probe from the Task 7 review.

    The prior manual probe changed an envelope on `get_product_evidence`, a
    single-contract capability, so the cross-contract comparison loop in
    `capability_parity_receipt` never executed. "Stayed green after an envelope
    change" therefore proved nothing about envelope independence.
    `explain_retrieval` is the only capability with two contract records
    (`explain_retrieval` and `inspect_retrieval_run`), so it is the only one
    that can exercise that loop.

    The paired negative -- that a `payload_schema` change between these same
    two contracts *does* raise -- is already covered by
    `test_payload_drift_between_surfaces_is_caught` above, which mutates
    `explain_retrieval`'s `payload_schema`; it is intentionally not duplicated
    here.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    # Non-vacuity witness: without >= 2 contracts for this capability, the
    # cross-contract loop never runs and the PASS below proves nothing.
    explain_contracts = [
        contract
        for contract in payload["contracts"]
        if contract["capability"] == "explain_retrieval"
    ]
    assert len(explain_contracts) >= 2, (
        "explain_retrieval must keep at least two contract records, or this "
        "independence proof is vacuous"
    )

    for contract in payload["contracts"]:
        if contract["name"] == "inspect_retrieval_run":
            contract["envelope_fields"]["mcp"].append("replay_trace")
            contract["output_schema"]["properties"]["replay_trace"] = {
                "type": ["string", "null"]
            }

    changed = tmp_path / "explain-envelope-independent.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("scripts.tool_contracts.CONTRACT_PATH", changed)

    capability_parity_receipt()


SKILL_CAPABILITIES = {
    "open_retrieval",
    "get_product_evidence",
    "compare_products",
    "explain_retrieval",
}


def test_the_skill_surface_exposes_four_capabilities():
    contracts = contracts_for_surface("skill")

    assert {contract["name"] for contract in contracts} == {
        "search_products",
        "get_product_evidence",
        "compare_products",
        "explain_retrieval",
    }
    assert all(contract["read_only"] for contract in contracts)


def test_skill_is_a_discoverable_standard_package():
    """A takeaway folder must be loadable as a skill, not only readable Markdown."""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert re.search(r"^name:\s+mosaic-hybrid-retrieval$", frontmatter, re.MULTILINE)
    assert re.search(r"^description:\s+\S", frontmatter, re.MULTILINE)


def test_skill_http_bindings_cover_every_operation_argument():
    """Every logical skill argument has exactly one executable HTTP destination."""
    receipt = validate_skill_http_bindings()

    assert receipt == {
        "operations": 4,
        "mapped_arguments": 21,
    }


def test_skill_http_binding_rejects_an_unmapped_argument():
    """Permanent falsifier for the binding gate: drop one real optional input."""
    bindings = copy.deepcopy(tool_contracts.SKILL_HTTP_BINDINGS)
    del bindings["search_products"]["body"]["authorized_limit"]

    with pytest.raises(ToolContractError, match="authorized_limit"):
        validate_skill_http_bindings(bindings=bindings)


def test_skill_http_binding_rejects_a_route_placeholder_without_a_mapping():
    """The route table cannot look executable while omitting a path argument."""
    bindings = copy.deepcopy(tool_contracts.SKILL_HTTP_BINDINGS)
    bindings["compare_products"]["path"] = {}

    with pytest.raises(ToolContractError, match="search_event_id"):
        validate_skill_http_bindings(bindings=bindings)


def test_skill_http_binding_rejects_a_flat_filter_body_destination():
    """Permanent falsifier: FastAPI requires filters.domain, not body.domain."""
    bindings = copy.deepcopy(tool_contracts.SKILL_HTTP_BINDINGS)
    bindings["search_products"]["body"]["domain"] = "domain"

    with pytest.raises(ToolContractError, match="absent from SearchRequest"):
        validate_skill_http_bindings(bindings=bindings)


def test_skill_http_binding_is_independent_of_mapping_order():
    """Reordering a JSON object is irrelevant to the executable binding."""
    bindings = copy.deepcopy(tool_contracts.SKILL_HTTP_BINDINGS)
    body = bindings["search_products"]["body"]
    bindings["search_products"]["body"] = dict(reversed(list(body.items())))

    assert validate_skill_http_bindings(bindings=bindings) == {
        "operations": 4,
        "mapped_arguments": 21,
    }


def test_skill_http_reference_is_generated_from_the_checked_binding():
    assert (
        SKILL_HTTP_REFERENCE_PATH.read_text(encoding="utf-8")
        == render_skill_http_reference()
    )


def test_synthesis_is_not_part_of_the_retrieval_skill():
    """Synthesis is orchestration. The skill stops at authorized evidence.

    Paired with a positive assertion on purpose: an absence-only check on
    `synthesize_cited_answer` and `inspect_retrieval_run` would pass
    identically on an empty or broken skill surface, proving nothing about
    what the surface actually contains.
    """
    names = {contract["name"] for contract in contracts_for_surface("skill")}

    assert names == {
        "search_products",
        "get_product_evidence",
        "compare_products",
        "explain_retrieval",
    }
    assert "synthesize_cited_answer" not in names
    assert "inspect_retrieval_run" not in names


def test_scoped_skill_operations_require_the_retrieval_scope():
    by_name = {
        contract["name"]: contract for contract in contracts_for_surface("skill")
    }

    for name in ("get_product_evidence", "compare_products"):
        required = by_name[name]["input_schema"]["required"]
        assert "retrieval_scope_id" in required, name

    explain = by_name["explain_retrieval"]["input_schema"]
    assert explain["required"] == ["retrieval_scope_id"]
    assert "search_event_id" not in explain["properties"], (
        "explain takes the scope itself, not a second arbitrary event id"
    )


def test_api_serves_the_skill_surface():
    from fastapi.testclient import TestClient

    from service.main import app

    payload = TestClient(app).get("/api/tools", params={"surface": "skill"}).json()

    assert payload["surface"] == "skill"
    assert len(payload["tools"]) == 4


def test_every_skill_capability_has_a_registered_route():
    """The HTTP badge in the Playground derives from this being true.

    Deliberately keeps its own hardcoded literals rather than reading
    `SKILL_ROUTES`, as an independent cross-check (house rule 5): two sources
    that must separately arrive at the same four paths is the point.
    `test_every_route_in_skill_routes_is_registered_on_the_app` below is the
    one that actually pins `SKILL_ROUTES` to this.
    """
    from service.main import app

    served = {route.path for route in app.routes if getattr(route, "path", None)}

    assert "/api/search" in served
    assert "/api/products/{product_id}/evidence" in served
    assert "/api/retrieval/events/{search_event_id}" in served
    assert "/api/retrieval/events/{search_event_id}/compare" in served


def test_every_route_in_skill_routes_is_registered_on_the_app():
    """Pin `SKILL_ROUTES` to what FastAPI actually serves.

    Reads `SKILL_ROUTES` directly, unlike the hardcoded cross-check above.
    """
    from service.main import app

    served = {route.path for route in app.routes if getattr(route, "path", None)}

    # Witness, independent of `served`: proves the loop below visits more than
    # zero routes rather than vacuously passing over an emptied dict.
    assert len(tool_contracts.SKILL_ROUTES) == 4, (
        f"expected exactly 4 SKILL_ROUTES entries, found "
        f"{len(tool_contracts.SKILL_ROUTES)}; recount if a skill capability "
        "was added or removed"
    )

    for name, route in tool_contracts.SKILL_ROUTES.items():
        _, path = route.split(" ", 1)
        assert path in served, (
            f"SKILL_ROUTES[{name!r}] is {route!r} but the FastAPI app does not "
            f"register {path!r}; fix: register that path, or correct "
            f"SKILL_ROUTES[{name!r}]"
        )


def test_skill_routes_key_set_matches_the_skill_surface_exactly():
    """House rule 5a: `SKILL_ROUTES` must be exhaustive over the skill surface.

    Equality, checked directly against `contracts_for_surface("skill")`, not a
    derivation `render_skill_contract` could also perform: `render_skill_contract`
    only raises when a skill name has no route (a missing key), never when
    `SKILL_ROUTES` carries a route for a name the skill surface does not
    expose, because it never looks that extra key up. Only this direct
    equality catches that second direction; see the two falsifiers below.
    """
    skill_names = {contract["name"] for contract in contracts_for_surface("skill")}

    # Witness, independent of SKILL_ROUTES: a literal, not a count re-derived
    # from the same predicate this test compares.
    assert len(skill_names) == 4, (
        f"expected exactly 4 skill-surface contracts, found {len(skill_names)}; "
        "recount if a skill capability was added or removed"
    )

    assert set(tool_contracts.SKILL_ROUTES) == skill_names, (
        f"SKILL_ROUTES keys are {sorted(tool_contracts.SKILL_ROUTES)} but the "
        f"skill surface exposes {sorted(skill_names)}; fix: add or remove "
        "SKILL_ROUTES entries in scripts/tool_contracts.py until the two sets "
        "match exactly"
    )


def test_skill_routes_exhaustiveness_rejects_an_unrouted_skill_capability(
    tmp_path, monkeypatch
):
    """Permanent falsifier, exhaustiveness failure direction one.

    Add a skill-surface contract whose name `SKILL_ROUTES` does not carry.
    Both the direct equality check above and `render_skill_contract` -- which
    now raises `ToolContractError` naming the missing route instead of a bare
    `KeyError` -- must catch this.
    """
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    ghost = copy.deepcopy(
        next(c for c in payload["contracts"] if c["name"] == "search_products")
    )
    ghost["name"] = "search_products_ghost"
    payload["contracts"].append(ghost)

    added = tmp_path / "unrouted-skill-capability.json"
    added.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(tool_contracts, "CONTRACT_PATH", added)

    skill_names = {
        contract["name"] for contract in tool_contracts.contracts_for_surface("skill")
    }
    assert "search_products_ghost" in skill_names
    assert set(tool_contracts.SKILL_ROUTES) != skill_names

    with pytest.raises(ToolContractError, match="SKILL_ROUTES has no entry"):
        tool_contracts.render_skill_contract()


def test_skill_routes_exhaustiveness_rejects_a_route_for_a_non_skill_name(
    monkeypatch,
):
    """Permanent falsifier, exhaustiveness failure direction two.

    A route entry naming a capability the skill surface does not expose must
    also fail the equality check. `render_skill_contract` cannot see this
    direction at all -- it only ever fails on a missing lookup, never on an
    unused extra key -- so this is the proof that the direct equality
    assertion, not the lookup path, is what is doing the exhaustiveness work.
    """
    bogus_routes = dict(tool_contracts.SKILL_ROUTES)
    bogus_routes["totally_bogus_capability"] = "GET /api/nonexistent"
    monkeypatch.setattr(tool_contracts, "SKILL_ROUTES", bogus_routes)

    skill_names = {
        contract["name"] for contract in tool_contracts.contracts_for_surface("skill")
    }
    assert set(tool_contracts.SKILL_ROUTES) != skill_names

    # render_skill_contract still succeeds: it never looks up the unused extra
    # key, which is exactly why the direct equality check above is required.
    tool_contracts.render_skill_contract()


#: Only the capabilities the packaged skill exposes. `synthesize_cited_answer`
#: is orchestration, outside the skill, and outside this gate.
GATED_CAPABILITIES = {
    "open_retrieval",
    "get_product_evidence",
    "compare_products",
    "explain_retrieval",
}

#: The response model each non-agent surface actually enforces.
SURFACE_MODELS = {
    ("open_retrieval", "mcp"): "SearchResponse",
    ("open_retrieval", "skill"): "SearchResponse",
    ("get_product_evidence", "mcp"): "ProductEvidenceResponse",
    ("get_product_evidence", "skill"): "ProductEvidenceResponse",
    ("explain_retrieval", "mcp"): "RetrievalRunResponse",
    ("explain_retrieval", "skill"): "RetrievalRunResponse",
    ("compare_products", "skill"): "ProductComparisonResponse",
}


def _agent_success_keys(tool_name: str) -> set[str]:
    """Keys of the success-path dict literals one agent tool returns.

    Success paths are the `return {...}` literals carrying `"ok": True`. Failure
    paths go through `_failure()`, which is a different declared shape and is not
    what the contract's payload describes.
    """
    module = ast.parse(
        (ROOT / "service" / "agent_tools.py").read_text(encoding="utf-8")
    )
    for node in module.body:
        if not isinstance(node, ast.FunctionDef) or node.name != tool_name:
            continue
        keys: set[str] = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return):
                continue
            if not isinstance(inner.value, ast.Dict):
                continue
            literal = {
                key.value: value
                for key, value in zip(inner.value.keys, inner.value.values)
                if isinstance(key, ast.Constant)
            }
            ok = literal.get("ok")
            if isinstance(ok, ast.Constant) and ok.value is True:
                keys |= set(literal)
        assert keys, f"found no success return in {tool_name}"
        return keys
    raise AssertionError(f"{tool_name} is not defined in service/agent_tools.py")


def test_returned_payload_matches_the_declared_contract():
    """Declarations must be true, not merely consistent with each other.

    Checks the payload's field set only. It does not check the internal shape of
    each field's value: the agent surface's `results` entries are
    `_product_for_model` projections rather than `ProductSummary`, and this gate
    makes no claim about that.

    Falsifier: rename any returned key without updating the contract.
    """
    from service import models

    checked = 0
    for contract in load_contracts():
        capability = contract["capability"]
        if capability not in GATED_CAPABILITIES:
            continue

        for surface in contract["surfaces"]:
            # The production projection, not a re-derivation. See the note above:
            # recomputing `payload | envelope` here would pass even if
            # `_project_output_schema` were deleted.
            projected = {
                item["name"]: item["output_schema"]
                for item in contracts_for_surface(surface)
            }[contract["name"]]
            declared = set(projected["properties"])
            required = set(projected.get("required", []))

            if surface == "agent":
                actual = _agent_success_keys(contract["name"])
            else:
                model_name = SURFACE_MODELS[(capability, surface)]
                actual = set(getattr(models, model_name).model_fields)

            checked += 1
            undeclared = actual - declared
            assert not undeclared, (
                f"{contract['name']} on {surface} returns {sorted(undeclared)}, "
                f"which the {surface} projection does not declare "
                f"{sorted(declared)}; fix: declare the field for that surface, "
                "or rename the return so the contract is true"
            )
            missing = required - actual
            assert not missing, (
                f"{contract['name']} on {surface} does not return required "
                f"{sorted(missing)}; found {sorted(actual)}; fix: return it or "
                "drop it from payload_schema.required"
            )

    # Independent witness, per house-standards rule 7: a literal, not a count
    # re-derived from the same predicate this loop filters on.
    #
    # 11 = search_products 3 (agent, mcp, skill) + get_product_evidence 3
    #    + compare_products 2 (agent, skill) + explain_retrieval 2 (agent, skill)
    #    + inspect_retrieval_run 1 (mcp). That last one is easy to miss: its
    #    capability is `explain_retrieval`, so it IS gated even though its wire
    #    name differs. Recount from the JSON if a surface is added or removed.
    assert checked == 11, (
        f"expected 11 gated capability/surface pairs, checked {checked}; "
        "fix: recount agent/mcp/skill declarations across the four gated "
        "capabilities, remembering inspect_retrieval_run carries the "
        "explain_retrieval capability, then update this literal"
    )


def test_every_gated_capability_is_actually_covered():
    """Exhaustiveness: the gate's allow-list must not silently shrink.

    House rule 5a. A gate whose scope is an enumerated list decays unless
    something forces the list to stay complete over its own domain.
    """
    skill_capabilities = {
        contract["capability"] for contract in contracts_for_surface("skill")
    }

    assert skill_capabilities == GATED_CAPABILITIES, (
        "the skill surface exposes a capability the return-shape gate does not "
        f"check; skill has {sorted(skill_capabilities)}, gate has "
        f"{sorted(GATED_CAPABILITIES)}"
    )


def test_skill_doc_contract_block_matches_the_registry():
    from scripts.tool_contracts import (
        SKILL_BEGIN,
        SKILL_END,
        SKILL_PATH,
        render_skill_contract,
    )

    text = SKILL_PATH.read_text(encoding="utf-8")
    start = text.index(SKILL_BEGIN) + len(SKILL_BEGIN)
    end = text.index(SKILL_END)

    assert text[start:end] == render_skill_contract(), (
        "SKILL.md's generated block drifted from "
        "db/config/agent_tool_contracts.json; run "
        "python scripts/tool_contracts.py --write"
    )


def test_skill_doc_names_every_skill_operation_and_no_others():
    """ "...and no others" is checked, not just asserted by the test's name.

    Scoped to the SKILL_BEGIN/SKILL_END block, not the whole file: the
    "Inputs" table just past `SKILL_END` also uses backtick-fenced first
    columns (`` | `query` | ... `` ), so a whole-file version of this same
    regex would pick up field names from that unrelated table and fail on
    perfectly good prose. Scoping to the generated block is what keeps the
    check from being brittle against ordinary Markdown elsewhere in the file.
    """
    from scripts.tool_contracts import SKILL_BEGIN, SKILL_END, SKILL_PATH

    text = SKILL_PATH.read_text(encoding="utf-8")
    start = text.index(SKILL_BEGIN) + len(SKILL_BEGIN)
    end = text.index(SKILL_END)
    block = text[start:end]

    expected = {
        "search_products",
        "get_product_evidence",
        "compare_products",
        "explain_retrieval",
    }
    named = set(re.findall(r"^\| `(\w+)` \|", block, flags=re.MULTILINE))

    # Witness: the regex matched a genuine multi-row table, not zero rows by a
    # broken pattern silently passing on an empty set.
    assert len(named) == 4, (
        f"expected the generated operations table to name exactly 4 "
        f"operations, found {sorted(named)}; check the row pattern against "
        "the current table shape"
    )
    assert named == expected, (
        f"the generated operations table names {sorted(named)} but the skill "
        f"surface is exactly {sorted(expected)}; fix: run "
        "python scripts/tool_contracts.py --write, or update the expected set "
        "here if the skill surface itself changed"
    )
    assert "synthesize_cited_answer" in text, (
        "SKILL.md must say synthesis is outside the skill, so it has to name it"
    )


def test_skill_doc_carries_the_two_rank_spaces():
    """Conflating the pool space with the granted space invents rank movement."""
    from scripts.tool_contracts import SKILL_PATH

    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "pre_rerank_rank" in text
    assert "authorized_limit" in text
    assert "candidate 27" in text, "the explain-does-not-authorize line is missing"


def test_skill_doc_holds_no_protocol_details():
    """A2A and AgentCore hosting belong in the deployment profile, not here.

    Falsifier: paste the Agent Card contract into SKILL.md and this fails.
    """
    from scripts.tool_contracts import SKILL_PATH

    text = SKILL_PATH.read_text(encoding="utf-8").lower()

    for forbidden in ("jsonrpc", "agent-card.json", "protocolversion", "arm64"):
        assert forbidden not in text, (
            f"SKILL.md mentions {forbidden!r}; move it to "
            "references/composition.md so the contract survives hosting changes"
        )


def test_skill_doc_uses_real_wire_field_names():
    """No aspirational names. `/api/search` returns `search_event_id`."""
    from scripts.tool_contracts import SKILL_PATH

    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "search_event_id" in text
    assert "candidate_limit" not in text, (
        "there is no candidate_limit field; the served window is `limit`"
    )


def test_composition_doc_states_no_a2a_endpoint_is_deployed():
    """A2A stays visibly honest: documented, never a claim it is running."""
    text = COMPOSITION_PATH.read_text(encoding="utf-8")

    assert "not deployed" in text.lower()
    assert "documentation profile" in text.lower()


def test_composition_doc_reports_adapter_asymmetry():
    """Shared capabilities do not imply every transport exposes four tools."""
    text = COMPOSITION_PATH.read_text(encoding="utf-8").lower()

    assert re.search(r"http\s+skill surface (?:exposes|has) four operations", text)
    assert re.search(r"mcp\s+has three", text)
    assert re.search(r"does\s+not expose `compare_products`", text)
    assert "regardless of which transport" not in text
    assert "same four capabilities" not in text


def test_read_only_claim_discloses_receipt_writes_and_non_idempotence():
    """Adopters need write capacity even though catalog records never mutate."""
    text = SKILL_PATH.read_text(encoding="utf-8").lower()

    assert "catalog-read-only" in text
    assert "no operation mutates catalog or business records" in text
    assert re.search(r"search\s+is\s+not idempotent", text)
    assert "retention" in text


def test_composition_doc_quotes_the_hosting_contract_accurately():
    """These are quoted facts, not paraphrase. Re-read the source to change them."""
    text = COMPOSITION_PATH.read_text(encoding="utf-8")

    for fact in (
        "/.well-known/agent-card.json",
        "JSON-RPC 2.0",
        "0.3.0",
        "9000",
        "0.0.0.0",
        "ARM64",
        '"status": "Healthy"',
    ):
        assert fact in text, fact


def test_no_a2a_dependency_entered_any_environment():
    """The reveal is a diagram. It must stay one.

    Falsifier: add a2a-sdk or strands[a2a] anywhere and this fails.

    Paired with a positive assertion on `pyproject.toml` so this cannot pass
    vacuously: an absence-only check would pass identically against a deleted
    or emptied manifest, proving nothing about what actually shipped.
    """
    checked = 0
    for path in (
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "mcp-server" / "pyproject.toml",
        ROOT / "config" / "requirements.txt",
    ):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "a2a-sdk" not in text, path
        assert "strands-agents[a2a]" not in text, path
        checked += 1

    # Witness, independent of the absence checks above: proves the loop
    # actually read four real manifests rather than skipping all of them.
    assert checked == 4, f"expected 4 dependency manifests to exist, found {checked}"

    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "httpx" in pyproject_text
    assert "strands-agents" in pyproject_text


def test_skill_doc_link_to_the_composition_doc_resolves():
    """All conditional guidance ships inside the participant takeaway folder."""
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "references/composition.md" in text
    assert "references/http-api.md" in text
    assert "references/adapting.md" in text
    assert COMPOSITION_PATH.exists()
    assert SKILL_HTTP_REFERENCE_PATH.exists()
    assert ADAPTATION_PATH.exists()


def test_adaptation_guide_separates_invariants_from_mosaic_choices():
    """The takeaway must teach reuse boundaries, not invite schema cloning."""
    text = ADAPTATION_PATH.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "## Keep these invariants" in text
    assert "## Replace these Mosaic choices" in text
    assert "before its candidate limit" in text
    assert "transport adapters thin" in lowered
    for mosaic_choice in (
        "postgresql `english`",
        "1,024 dimensions",
        "single-attendee uuid handles",
        "mosaic missions",
    ):
        assert mosaic_choice in lowered
    assert "do not copy mosaic's numbers as production defaults" in lowered


#: references/composition.md Section 3's post-reframing claim. Section 3 no
#: longer asserts that any specific mechanic is "genuinely unobservable" --
#: the fix that first tried that framing (this file's previous revision)
#: shipped a false claim of its own (the vector arm's HNSW identity is a
#: literal field name, `hnsw_settings`), and a second, structurally different
#: hole surfaced after that: `plan_json` is typed `dict[str, Any]`, so no walk
#: over field *names* could ever see what its runtime *content* names once a
#: plan is captured. Measured against the live cluster, a captured plan
#: resolves `product_document_embedding_hnsw_cosine_idx` as an `Index Scan`,
#: while the lexical and trigram arms stay opaque `Function Scan` nodes over
#: `search_fts` and `search_trigram`, naming no index at all. Both halves of
#: that are invisible to a name walk. Section 3 now claims the other
#: direction:
#: encapsulation is not a promise that any mechanic can never be inspected.
#: This dict is hand-authored from that same source-level verification, not
#: extracted from the document's prose -- a gate that parsed Section 3's own
#: claims and checked them against itself would agree with itself by
#: construction, honest or not; see
#: `_assert_document_acknowledges_inspectable_terms`.
_ACKNOWLEDGED_INSPECTABLE_TERMS = {
    "plan_json": "explain_retrieval, once a plan has been captured",
    "diagnostics": "search_products by default, and explain_retrieval always",
    "hnsw_settings": "explain_retrieval, naming the vector arm's HNSW tuning",
}

#: Phrasing this document must not reintroduce. Section 3's retired framing
#: used exactly this language to claim specific mechanics could never be
#: observed; `plan_json` proved that framing false rather than just one
#: bullet within it, so the framing itself, not only its inventory, is
#: retired. See `_assert_document_retired_unobservability_claims`.
_RETIRED_UNOBSERVABILITY_PHRASES = ("genuinely unobservable",)


def _nested_pydantic_models(annotation: object) -> "typing.Iterator[type]":
    """Yield every Pydantic model type reachable from a field annotation.

    Walks `list[...]`, `dict[...]`, `X | None`, and other generic annotations
    via `typing.get_args`, so a model nested inside a container is found the
    same way a client parsing the JSON would encounter it.
    """
    from pydantic import BaseModel

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _nested_pydantic_models(arg)


def _model_field_names(model: type, seen: set[type] | None = None) -> set[str]:
    """Recursively collect every field name declared by a model and its nesting.

    `RetrievalRunResponse` only declares `run` and `candidates` at its own
    top level; the fields that actually matter for this gate, like
    `SearchEventRecord.hnsw_settings`, live one or more levels down. A gate
    that only read `model_fields` at the top level would never see them.
    """
    if seen is None:
        seen = set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for field_name, field in model.model_fields.items():
        names.add(field_name)
        for nested in _nested_pydantic_models(field.annotation):
            names |= _model_field_names(nested, seen)
    return names


def _dict_literal_keys(source: str, variable_name: str) -> set[str]:
    """Extract the literal string keys of one `variable_name = {...}` assignment.

    Parses the AST rather than importing the module, per house rule 3's spirit
    of reading the production source directly: `service/retrieval.py` needs a
    live connection factory to import cleanly in some configurations, and the
    keys of a dict literal are visible without ever running the module.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != variable_name:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError(f"no dict literal assignment to {variable_name!r} found")


def _assert_document_acknowledges_inspectable_terms(
    text: str,
    field_names: set[str],
    terms: dict[str, str] | None = None,
) -> None:
    """Raise if an acknowledged term is not a real field, or is never named.

    Both directions matter. A term this document credits as inspectable that
    is not an actual field name on a real skill response model would be a
    fabricated transparency claim -- overclaiming is exactly as dishonest as
    the underclaiming the retired gate caught. A real field the acknowledgment
    list names but the document's own text never mentions would be true only
    by accident, not because Section 3 actually says so.

    `terms` defaults to the real, hand-authored `_ACKNOWLEDGED_INSPECTABLE_
    TERMS`; the falsifiers below pass a synthetic dict instead, the same
    technique the retired hidden-field gate's falsifiers used against
    `_assert_no_hidden_field_names`.
    """
    if terms is None:
        terms = _ACKNOWLEDGED_INSPECTABLE_TERMS
    lowered_text = text.lower()
    lowered_names = {name.lower() for name in field_names}
    for term, surface in terms.items():
        assert term in lowered_names, (
            f"{term!r} is claimed inspectable via {surface}, but no field "
            f"named {term!r} was found on any of the four skill response "
            "models; fix the claim in references/composition.md, or find "
            "where the field actually lives"
        )
        assert term in lowered_text, (
            f"references/composition.md never names {term!r}, but it is a "
            f"real field returned via {surface}; Section 3 must acknowledge "
            "it explicitly, not leave it true only by omission"
        )


def _assert_document_retired_unobservability_claims(text: str) -> None:
    """Raise if the document reasserts an absolute "cannot be observed" claim.

    The acknowledgment check above cannot see this direction: a document
    could name every acknowledged term correctly and still also claim some
    other mechanic is "genuinely unobservable" alongside them. This is the
    half that catches that.
    """
    lowered = text.lower()
    for phrase in _RETIRED_UNOBSERVABILITY_PHRASES:
        assert phrase not in lowered, (
            f"references/composition.md contains {phrase!r}; Section 3 was "
            "reframed away from absolute unobservability claims after "
            "plan_json proved one false -- do not reintroduce this framing"
        )


def test_section_3_acknowledges_inspectable_fields_and_drops_absolute_claims():
    """Finding 4 gate: pin Section 3's reframed claim to the real models.

    Finding 3's gate (the previous version of this test) asserted specific
    mechanics were absent from every field *name* across the four skill
    response models. That gate was structurally blind to this task's hole:
    `plan_json` is a real, intentional field typed `dict[str, Any]`, so no
    field-name walk could ever see what its runtime *content* names once a
    plan is captured -- measured, a captured plan resolves the HNSW index
    behind the vector arm as an `Index Scan` and names no index for the
    lexical or trigram arms, which stay opaque `Function Scan` nodes. A name
    walk only ever sees the key `plan_json` itself, never what a captured
    plan happens to contain.

    Section 3 no longer claims any specific mechanic can never be observed;
    it claims encapsulation is not secrecy, and it names `plan_json`,
    `diagnostics`, and `hnsw_settings` as fields a caller can already read.
    This checks that claim honestly in both directions -- every acknowledged
    term is a real field on a real skill response model, the document
    actually says so, and the retired "genuinely unobservable" framing has
    not crept back in -- and keeps the one Finding-3-era claim that survives
    the reframing unchanged: `candidate_counts` still only ever names the
    semantic arm the generic `semantic_in_pool`.
    """
    from service import models

    skill_response_models = {
        "search_products": models.SearchResponse,
        "get_product_evidence": models.ProductEvidenceResponse,
        "compare_products": models.ProductComparisonResponse,
        "explain_retrieval": models.RetrievalRunResponse,
    }

    all_field_names: set[str] = set()
    for model in skill_response_models.values():
        all_field_names |= _model_field_names(model)

    # Witness, independent of the acknowledgment loop below (house rule 7): a
    # literal count, not derived from the same predicate that loop checks. If
    # the recursive nested-model walk above stopped short -- say, it silently
    # dropped nested models -- this would still catch it, because the loop
    # would then be examining far fewer names than the schema actually
    # declares. Measured against the real models at the time this gate was
    # written: 108.
    assert len(all_field_names) >= 100, (
        f"expected at least 100 field names across the four skill response "
        f"models' full nesting, collected {len(all_field_names)}; the "
        "recursive walk in _model_field_names may have stopped early"
    )

    retrieval_source = (ROOT / "service" / "retrieval.py").read_text(encoding="utf-8")
    candidate_count_keys = _dict_literal_keys(retrieval_source, "candidate_counts")
    assert candidate_count_keys == {
        "fused_pool",
        "fts_in_pool",
        "trigram_in_pool",
        "semantic_in_pool",
    }, (
        f"candidate_counts now has keys {sorted(candidate_count_keys)}; if a "
        "new key names pgvector or hnsw, references/composition.md Section 3 "
        "needs the same correction this gate was written to catch"
    )

    text = COMPOSITION_PATH.read_text(encoding="utf-8")
    # Witness for the text side, independent of the acknowledgment loop below:
    # proves the document was actually read as real, structured prose, not an
    # empty or truncated file.
    assert text.count("## ") >= 5, "references/composition.md read unexpectedly short"

    _assert_document_acknowledges_inspectable_terms(text, all_field_names)
    _assert_document_retired_unobservability_claims(text)


def test_inspectable_acknowledgment_gate_is_red_at_birth_for_a_fabricated_term():
    """Permanent falsifier, direction one: an acknowledged term that isn't real.

    Proves the "must be a real field" half of
    `_assert_document_acknowledges_inspectable_terms` actually discriminates.
    Passes a synthetic `terms` dict directly rather than editing
    `service/models.py`, which this task's constraints forbid touching -- the
    same technique the contract-parity tests earlier in this file use with a
    mutated copy of the JSON registry instead of the real one.
    """
    with pytest.raises(AssertionError, match="fabricated_diagnostic_field"):
        _assert_document_acknowledges_inspectable_terms(
            "fabricated_diagnostic_field is fully inspectable",
            {"search_event_id", "results"},
            terms={"fabricated_diagnostic_field": "nowhere real"},
        )


def test_inspectable_acknowledgment_gate_is_red_at_birth_for_a_silent_claim():
    """Permanent falsifier, direction two: a real field the document never names.

    The paired failure direction: the term is genuinely a field name, but the
    document text never mentions it, so the acknowledgment would be true only
    by accident rather than because Section 3 actually says so.
    """
    with pytest.raises(AssertionError, match="hnsw_settings"):
        _assert_document_acknowledges_inspectable_terms(
            "this document never mentions the vector index tuning field",
            {"hnsw_settings", "search_event_id"},
            terms={"hnsw_settings": "explain_retrieval"},
        )


def test_inspectable_acknowledgment_gate_is_independent_of_an_unrelated_new_field():
    """Independence proof for the acknowledgment half (house rule 7).

    An unrelated new field name -- the kind of ordinary addition a future
    pagination feature might make -- added on top of the real document and
    the real models must not trip the gate. Without this, a gate that always
    failed regardless of input would pass both falsifiers above for the wrong
    reason.
    """
    from service import models

    skill_response_models = {
        "search_products": models.SearchResponse,
        "get_product_evidence": models.ProductEvidenceResponse,
        "compare_products": models.ProductComparisonResponse,
        "explain_retrieval": models.RetrievalRunResponse,
    }
    all_field_names: set[str] = set()
    for model in skill_response_models.values():
        all_field_names |= _model_field_names(model)

    text = COMPOSITION_PATH.read_text(encoding="utf-8")
    _assert_document_acknowledges_inspectable_terms(
        text, all_field_names | {"result_page_token"}
    )


def test_retired_unobservability_guard_is_red_at_birth():
    """Permanent falsifier for the retirement guard.

    Proves `_assert_document_retired_unobservability_claims` actually
    discriminates, by reintroducing the exact phrase Section 3's retired
    framing used to claim a specific mechanic could never be observed.
    """
    with pytest.raises(AssertionError, match="genuinely unobservable"):
        _assert_document_retired_unobservability_claims(
            "the fusion formula remains genuinely unobservable to any caller"
        )


def test_retired_unobservability_guard_is_independent_of_ordinary_prose():
    """Independence proof for the retirement guard (house rule 7).

    Ordinary prose that discusses inspectability without the retired absolute
    phrasing must not trip the guard.
    """
    _assert_document_retired_unobservability_claims(
        "plan_json is inspectable once a plan has been captured separately"
    )
