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
REQUIRED_RELATIONS = {
    "change_confirmed",
    "change_ruled_out",
    "blocked_by_change",
    "observed_during",
}


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def fail(message: str) -> None:
    raise SystemExit(f"REMEDY: {message}")


def load_run(receipt_path: str) -> dict[str, Any]:
    receipt = load(receipt_path)
    required = {
        "run_suffix",
        "incident_key",
        "unsafe_change_key",
        "analyze_change_key",
        "lock_key",
    }
    missing = sorted(required - receipt.keys())
    if missing:
        fail(f"the indexing receipt is missing: {missing}")
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


def run_identifiers(receipt: dict[str, Any]) -> set[str]:
    return {
        receipt["incident_key"],
        receipt["unsafe_change_key"],
        receipt["analyze_change_key"],
        receipt["lock_key"],
    }


def is_run_key(external_key: Any, receipt: dict[str, Any]) -> bool:
    if external_key in run_identifiers(receipt):
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
    receipt = load_run(receipt_path)
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
    receipt = load_run(receipt_path)
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
    receipt = load_run(receipt_path)
    plan = load(plan_path)
    traversal = load(traversal_path)
    comparison = load(comparison_path)

    identified_keys = set(plan.get("identified_keys", []))
    missing_identifiers = sorted(run_identifiers(receipt) - identified_keys)
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
    missing_traversal = sorted(REQUIRED_RELATIONS - traversal_relations)
    if missing_traversal:
        fail(f"relationship traversal is missing: {missing_traversal}")
    missing_comparison = sorted(REQUIRED_RELATIONS - comparison_relations)
    if missing_comparison:
        fail(f"source comparison is missing: {missing_comparison}")

    print(
        "OK: the plan covers the captured incident, change, and lock evidence, "
        "and the authoritative graph confirms all three measured relationships"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--receipt",
        required=True,
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
    return result


def main() -> None:
    args = parser().parse_args()
    if args.checkpoint == "filter":
        check_filter(args.baseline, args.filtered, args.receipt)
    elif args.checkpoint == "fusion":
        check_fusion(args.baseline, args.tuned, args.receipt)
    else:
        check_agent(
            args.plan,
            args.traversal,
            args.comparison,
            args.receipt,
        )


if __name__ == "__main__":
    main()
