#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any


PARTICIPANT_SOURCE_SYSTEM = "pg_incident_capture"
REQUIRED_KINDS = {
    "incident",
    "change",
    "lock_evidence",
    "telemetry",
}
WAVE_A_REQUIRED_RELATIONS = {
    "change_confirmed",
    "change_ruled_out",
    "blocked_by_change",
    "observed_during",
}
WAVE_A_TRAVERSAL_RELATIONS = {
    "change_confirmed",
    "change_ruled_out",
    "observed_during",
}
WAVE_B_REQUIRED_RELATIONS = {"change_validates"}


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def fail(message: str) -> None:
    raise SystemExit(f"REMEDY: {message}")


def load_wave_a_receipt(receipt_path: str) -> dict[str, Any]:
    receipt = load(receipt_path)
    required = {
        "wave",
        "run_suffix",
        "incident_key",
        "unsafe_change_key",
        "analyze_change_key",
        "lock_key",
    }
    missing = sorted(required - receipt.keys())
    if missing:
        fail(f"the indexing receipt is missing: {missing}")
    if receipt["wave"] != "A":
        fail("Labs 2 and 3 require a Wave A diagnostic receipt")
    suffix = str(receipt["run_suffix"])
    expected = {
        "incident_key": f"INC-{suffix}",
        "unsafe_change_key": f"CHG-{suffix}-01",
        "analyze_change_key": f"CHG-{suffix}-02",
        "lock_key": f"LOCK-{suffix}-01",
    }
    if not re.fullmatch(r"[A-F0-9]{8}", suffix) or any(
        receipt[name] != value for name, value in expected.items()
    ):
        fail("the indexing receipt does not contain one valid run-derived identity")
    return receipt


def load_wave_b_receipt(receipt_path: str) -> dict[str, Any]:
    receipt = load(receipt_path)
    required = {
        "wave",
        "run_suffix",
        "incident_key",
        "validation_change_key",
    }
    missing = sorted(required - receipt.keys())
    if missing:
        fail(f"the validation receipt is missing: {missing}")
    if receipt["wave"] != "B":
        fail("validation requires a Wave B receipt")
    suffix = str(receipt["run_suffix"])
    if (
        not re.fullmatch(r"[A-F0-9]{8}", suffix)
        or receipt["validation_change_key"] != f"CHG-{suffix}-01"
    ):
        fail("the Wave B receipt does not contain one valid validation change")
    return receipt


def wave_a_identifiers(receipt: dict[str, Any]) -> set[str]:
    return {
        receipt["incident_key"],
        receipt["unsafe_change_key"],
        receipt["analyze_change_key"],
        receipt["lock_key"],
    }


def is_run_key(external_key: Any, receipt: dict[str, Any]) -> bool:
    if external_key in wave_a_identifiers(receipt):
        return True
    return bool(
        isinstance(external_key, str)
        and re.fullmatch(
            rf"TEL-{re.escape(receipt['run_suffix'])}-[A-Z]+[0-9]+",
            external_key,
        )
    )


def validate_live_results(
    payload: dict[str, Any],
    label: str,
    receipt: dict[str, Any],
) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    if not results:
        fail(f"the {label} response returned no participant evidence")
    wrong_sources = [
        row.get("external_key")
        for row in results
        if row.get("source_system") != PARTICIPANT_SOURCE_SYSTEM
    ]
    if wrong_sources:
        fail(
            f"the {label} response included candidates outside "
            f"{PARTICIPANT_SOURCE_SYSTEM}: {wrong_sources}"
        )
    unexpected_keys = sorted(
        {
            row.get("external_key")
            for row in results
            if not is_run_key(row.get("external_key"), receipt)
        }
    )
    if unexpected_keys:
        fail(f"the {label} response included non-capture evidence: {unexpected_keys}")
    return results


def check_filter(
    baseline_path: str,
    filtered_path: str,
    receipt_path: str,
) -> None:
    receipt = load_wave_a_receipt(receipt_path)
    baseline = validate_live_results(
        load(baseline_path), "unfiltered kind search", receipt
    )
    filtered = validate_live_results(
        load(filtered_path), "change-filtered search", receipt
    )
    baseline_kinds = {row.get("evidence_kind") for row in baseline}
    if "change" not in baseline_kinds or baseline_kinds <= {"change"}:
        fail("the unfiltered response must contain change and non-change evidence")
    wrong_kinds = sorted(
        {
            str(row.get("evidence_kind"))
            for row in filtered
            if row.get("evidence_kind") != "change"
        }
    )
    if wrong_kinds:
        fail(f"the kind filter retained non-change evidence: {wrong_kinds}")
    expected_changes = {
        receipt["unsafe_change_key"],
        receipt["analyze_change_key"],
    }
    filtered_keys = {row.get("external_key") for row in filtered}
    missing_changes = sorted(expected_changes - filtered_keys)
    if missing_changes:
        fail(f"the kind filter omitted measured changes: {missing_changes}")
    print(
        "OK: the unfiltered live search returned "
        f"{len(baseline_kinds)} evidence kinds; the database-side kind filter "
        f"retained only {len(filtered)} measured changes from this capture"
    )


def rrf_for(row: dict[str, Any], knobs: dict[str, Any]) -> float:
    positions = row["explanation"]["positions"]
    weights = knobs["weights"]
    rrf_k = knobs["rrf_k"]
    arms = (
        ("text", "full_text"),
        ("vector", "semantic"),
        ("fuzzy", "fuzzy"),
    )
    return sum(
        0.0
        if positions.get(position_name) is None
        else float(weights[weight_name]) / (rrf_k + positions[position_name])
        for weight_name, position_name in arms
    )


def validate_rrf(payload: dict[str, Any]) -> None:
    knobs = payload["knobs"]
    for row in payload.get("results", []):
        recomputed = rrf_for(row, knobs)
        if not math.isclose(
            recomputed,
            float(row["rrf_score"]),
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            fail(
                f"{row['external_key']} stored RRF {row['rrf_score']} "
                f"does not match recomputed {recomputed}"
            )


def check_fusion(
    baseline_path: str,
    tuned_path: str,
    receipt_path: str,
) -> None:
    receipt = load_wave_a_receipt(receipt_path)
    baseline = load(baseline_path)
    tuned = load(tuned_path)
    baseline_results = validate_live_results(
        baseline, "baseline fusion", receipt
    )
    tuned_results = validate_live_results(tuned, "tuned fusion", receipt)
    validate_rrf(baseline)
    validate_rrf(tuned)

    if baseline["knobs"]["weights"] != {
        "text": 2.0,
        "vector": 1.0,
        "fuzzy": 1.0,
    }:
        fail("the baseline response does not carry the default 2:1:1 weights")
    if tuned["knobs"]["weights"] != {
        "text": 0.0,
        "vector": 4.0,
        "fuzzy": 0.0,
    }:
        fail("set the tuned request weights to text=0, vector=4, fuzzy=0")

    baseline_keys = [row["external_key"] for row in baseline_results]
    tuned_keys = [row["external_key"] for row in tuned_results]

    print(
        "OK: every stored RRF score recomputes from its arm positions; "
        f"observed baseline top={baseline_keys[:3]}, "
        f"observed semantic-only top={tuned_keys[:3]}"
    )


def check_agent(
    plan_path: str,
    traversal_path: str,
    comparison_path: str,
    receipt_path: str,
) -> None:
    receipt = load_wave_a_receipt(receipt_path)
    plan = load(plan_path)
    traversal = load(traversal_path)
    comparison = load(comparison_path)

    identified_keys = set(plan.get("identified_keys", []))
    missing_identifiers = sorted(wave_a_identifiers(receipt) - identified_keys)
    if missing_identifiers:
        fail(f"the evidence plan is missing identifiers: {missing_identifiers}")

    kinds = {
        kind
        for subquestion in plan.get("subquestions", [])
        for kind in subquestion.get("required_kinds", [])
    }
    missing_kinds = sorted(REQUIRED_KINDS - kinds)
    if missing_kinds:
        fail(f"the evidence plan is missing required kinds: {missing_kinds}")

    traversal_relations = {
        row.get("via_relation")
        for row in traversal.get("reached", [])
        if row.get("via_relation")
    }
    comparison_relations = {
        row.get("relation") for row in comparison.get("relationships", [])
    }
    # Traversal returns a deduplicated spanning tree. The backfill change is
    # directly reachable from the incident, so the tree cannot also report its
    # alternate lock-to-change edge. Comparison validates that full edge set.
    missing_traversal = sorted(
        WAVE_A_TRAVERSAL_RELATIONS - traversal_relations
    )
    if missing_traversal:
        fail(f"relationship traversal is missing: {missing_traversal}")
    missing_comparison = sorted(WAVE_A_REQUIRED_RELATIONS - comparison_relations)
    if missing_comparison:
        fail(f"source comparison is missing: {missing_comparison}")

    print(
        "OK: the plan covers the captured incident, change, and lock evidence, "
        "and the authoritative graph confirms all three measured relationships"
    )


def check_validation(
    comparison_path: str,
    wave_a_receipt_path: str,
    wave_b_receipt_path: str,
) -> None:
    wave_a = load_wave_a_receipt(wave_a_receipt_path)
    wave_b = load_wave_b_receipt(wave_b_receipt_path)
    if wave_a["incident_key"] != wave_b["incident_key"]:
        fail("the Wave B validation receipt names a different incident")
    if wave_a["run_suffix"] == wave_b["run_suffix"]:
        fail("Wave B must have its own capture-derived run suffix")
    comparison = load(comparison_path)
    relations = {
        row.get("relation") for row in comparison.get("relationships", [])
    }
    missing = sorted(WAVE_B_REQUIRED_RELATIONS - relations)
    if missing:
        fail(f"validation evidence is missing: {missing}")
    print(
        "OK: Wave B added a validation relationship for the same incident "
        "without replacing the Wave A diagnostic evidence"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--receipt",
        help="indexing-receipt-<run-suffix>.json from the live orchestrator",
    )
    subparsers = result.add_subparsers(dest="checkpoint", required=True)

    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument("baseline")
    filter_parser.add_argument("filtered")

    fusion_parser = subparsers.add_parser("fusion")
    fusion_parser.add_argument("baseline")
    fusion_parser.add_argument("tuned")

    agent_parser = subparsers.add_parser("agent")
    agent_parser.add_argument("plan")
    agent_parser.add_argument("traversal")
    agent_parser.add_argument("comparison")

    validation_parser = subparsers.add_parser("validation")
    validation_parser.add_argument("comparison")
    validation_parser.add_argument("wave_a_receipt")
    validation_parser.add_argument("wave_b_receipt")
    return result


def main() -> None:
    command_parser = parser()
    args = command_parser.parse_args()
    if args.checkpoint != "validation" and not args.receipt:
        command_parser.error("--receipt is required for filter, fusion, and agent")
    if args.checkpoint == "filter":
        check_filter(args.baseline, args.filtered, args.receipt)
    elif args.checkpoint == "fusion":
        check_fusion(args.baseline, args.tuned, args.receipt)
    elif args.checkpoint == "agent":
        check_agent(
            args.plan,
            args.traversal,
            args.comparison,
            args.receipt,
        )
    else:
        check_validation(
            args.comparison,
            args.wave_a_receipt,
            args.wave_b_receipt,
        )


if __name__ == "__main__":
    main()
