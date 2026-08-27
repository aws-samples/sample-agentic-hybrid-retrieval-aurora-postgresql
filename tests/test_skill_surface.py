"""Capability-keyed contract parity across surfaces."""

import json
from pathlib import Path

import pytest

from scripts.tool_contracts import (
    CONTRACT_PATH,
    ToolContractError,
    capability_parity_receipt,
    load_contracts,
)

ROOT = Path(__file__).resolve().parents[1]


def test_every_contract_declares_a_capability():
    for contract in load_contracts():
        assert contract["capability"], contract["name"]


def test_explain_is_one_capability_under_two_wire_names():
    by_name = {contract["name"]: contract for contract in load_contracts()}

    assert by_name["explain_retrieval"]["capability"] == "explain_retrieval"
    assert by_name["inspect_retrieval_run"]["capability"] == "explain_retrieval"
    assert by_name["search_products"]["capability"] == "open_retrieval"


def test_shared_capabilities_agree_on_their_semantic_payload():
    receipt = capability_parity_receipt()

    assert "explain_retrieval" in receipt["shared_capabilities"]
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

    with pytest.raises(ToolContractError, match="payload_schema"):
        capability_parity_receipt()
