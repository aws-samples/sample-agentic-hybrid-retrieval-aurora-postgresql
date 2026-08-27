"""Capability-keyed contract parity across surfaces."""

import json

import pytest

from scripts.tool_contracts import (
    CONTRACT_PATH,
    ToolContractError,
    capability_parity_receipt,
    contracts_for_surface,
    load_contracts,
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


def test_synthesis_is_not_part_of_the_retrieval_skill():
    """Synthesis is orchestration. The skill stops at authorized evidence."""
    names = {contract["name"] for contract in contracts_for_surface("skill")}

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
    """The HTTP badge in the Playground derives from this being true."""
    from service.main import app

    served = {route.path for route in app.routes if getattr(route, "path", None)}

    assert "/api/search" in served
    assert "/api/products/{product_id}/evidence" in served
    assert "/api/retrieval/events/{search_event_id}" in served
    assert "/api/retrieval/events/{search_event_id}/compare" in served
