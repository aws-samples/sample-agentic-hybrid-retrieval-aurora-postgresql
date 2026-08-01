#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


TARGET_CLUSTER = "checkout-prod-cluster-01"
STAGING_KEYS = {"CHG-1840", "INC-2044"}
REQUIRED_KINDS = {
    "incident",
    "change",
    "support_case",
    "runbook",
    "lock_evidence",
}
REQUIRED_RELATIONS = {"change_confirmed", "change_ruled_out"}
REQUIRED_IDENTIFIERS = {"CHG-1842", "INC-2047"}
BASELINE_LEADER = "INC-2047"
SEMANTIC_LEADER = "CASE-7419"


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def fail(message: str) -> None:
    raise SystemExit(f"REMEDY: {message}")


def check_filter(before_path: str, after_path: str) -> None:
    before = load(before_path).get("results", [])
    after = load(after_path).get("results", [])
    before_keys = {row.get("external_key") for row in before}

    if not (before_keys & STAGING_KEYS):
        fail("the unfiltered response did not expose the seeded staging distractor")
    if not after:
        fail("the filtered response returned no evidence")
    leaked = [
        row.get("external_key")
        for row in after
        if row.get("cluster_id") != TARGET_CLUSTER
    ]
    if leaked:
        fail(f"cluster filtering still returned out-of-scope evidence: {leaked}")

    print(
        "OK: the unfiltered run exposed the staging distractor and "
        f"all {len(after)} filtered rows belong to {TARGET_CLUSTER}"
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


def check_fusion(baseline_path: str, tuned_path: str) -> None:
    baseline = load(baseline_path)
    tuned = load(tuned_path)
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

    baseline_keys = [row["external_key"] for row in baseline.get("results", [])]
    tuned_keys = [row["external_key"] for row in tuned.get("results", [])]
    if not baseline_keys or baseline_keys[0] != BASELINE_LEADER:
        fail(f"the baseline fused leader must be {BASELINE_LEADER}")
    if not tuned_keys or tuned_keys[0] != SEMANTIC_LEADER:
        fail(f"the semantic-only leader must be {SEMANTIC_LEADER}")

    print(
        "OK: every stored RRF score recomputes from its arm positions; "
        f"baseline top={baseline_keys[:3]}, semantic-only top={tuned_keys[:3]}"
    )


def check_agent(plan_path: str, traversal_path: str, comparison_path: str) -> None:
    plan = load(plan_path)
    traversal = load(traversal_path)
    comparison = load(comparison_path)

    identified_keys = set(plan.get("identified_keys", []))
    missing_identifiers = sorted(REQUIRED_IDENTIFIERS - identified_keys)
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
        "OK: the plan covers cause, impact, and remediation, and the "
        "authoritative graph confirms one change while ruling out the other"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="checkpoint", required=True)

    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument("before")
    filter_parser.add_argument("after")

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
        check_filter(args.before, args.after)
    elif args.checkpoint == "fusion":
        check_fusion(args.baseline, args.tuned)
    else:
        check_agent(args.plan, args.traversal, args.comparison)


if __name__ == "__main__":
    main()
