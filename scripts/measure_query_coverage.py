#!/usr/bin/env python3
"""Refresh vocabulary observations after a catalog change, preserving expectations."""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.retrieval_profile import load_profile
from service import coverage
from service.config import get_settings
from service.db import connect


def measure_cases(cases: list[dict], *, assess, metadata: dict) -> list[dict]:
    """Measure every declared case, refusing to revise its expected behavior."""
    if not cases:
        raise ValueError(
            "Coverage witness rule: no cases; restore the coverage query set."
        )
    measured = copy.deepcopy(cases)
    for case in measured:
        result = assess(case["query"])
        if (
            result.confidence != case["expected_confidence"]
            or (
                case["expected_unmatched_terms"]
                and result.unmatched_terms != case["expected_unmatched_terms"]
            )
            or (case["expected_confidence"] == "grounded" and result.unmatched_terms)
        ):
            raise ValueError(
                f"Coverage expectation rule: {case['query_id']} returned "
                f"{result.confidence}/{result.unmatched_terms}; expected "
                f"{case['expected_confidence']}/{case['expected_unmatched_terms']}. "
                "Inspect the catalog and coverage behavior before recording a new measurement."
            )
        terms = []
        for term in result.terms:
            item = {
                "token": term.token,
                "kind": term.token_kind,
                "ndoc": term.ndoc,
                "verdict": term.verdict,
            }
            if term.closest_lexeme is not None:
                item["closest"] = term.closest_lexeme
                item["similarity"] = round(float(term.closest_similarity), 3)
            terms.append(item)
        if not terms:
            raise ValueError(
                f"Coverage term witness rule: {case['query_id']} returned no terms; "
                "restore the vocabulary and rerun production coverage."
            )
        case["measured"] = {
            **metadata,
            "confidence": result.confidence,
            "unmatched_terms": result.unmatched_terms,
            "terms": terms,
        }
        case["verified_against_catalog"] = True
    return measured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    path = ROOT / "data/evals/coverage_queries.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM mosaic_search.product_document"
        ).fetchone()["n"]
    if not count:
        raise ValueError(
            "Coverage catalog rule: zero products; load the Aurora catalog."
        )
    measured = measure_cases(
        cases,
        assess=coverage.assess,
        metadata={
            "measured_on": datetime.datetime.now(datetime.UTC).date().isoformat(),
            "cluster": f"Amazon Aurora PostgreSQL, {count:,} products",
            "dataset_manifest_sha256": get_settings().dataset_manifest_sha256,
            "similarity_floor": load_profile().coverage_similarity_floor,
        },
    )
    if args.write:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in measured)
        )
        temporary.replace(path)
    print(f"Measured {len(measured)} coverage cases; declared expectations unchanged.")
    print(
        "Saved observations." if args.write else "Preview only; pass --write to save."
    )


if __name__ == "__main__":
    main()
