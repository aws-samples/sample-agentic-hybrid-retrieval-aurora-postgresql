#!/usr/bin/env python3
"""Validate each DAT410 lab through the production HTTP and retrieval paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "data" / "evals" / "mosaic_labs_missions.json"


class LabValidationError(RuntimeError):
    """A lab failed one of its participant-visible acceptance checks."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LabValidationError(message)


def _request(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise LabValidationError(
            f"{path} returned HTTP {error.code}: {detail}"
        ) from error
    except URLError as error:
        raise LabValidationError(
            f"{path} is unavailable at {base_url}: {error.reason}; "
            "start mosaic-api and retry"
        ) from error


def _mission(stage: str) -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return next(item for item in contract["missions"] if item["stage"] == stage)


def _case(case_id: str) -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    cases = contract["missions"] + contract["supporting_checks"]
    return next(item for item in cases if item["id"] == case_id)


def _search(base_url: str, mission: dict[str, Any]) -> dict[str, Any]:
    return _request(
        base_url,
        "/api/search",
        {
            "query": mission["query"],
            "filters": mission["filters"],
            "limit": mission["top_k"],
            "include_diagnostics": True,
            "rerank": True,
        },
    )


def _eligible(result: dict[str, Any], filters: dict[str, Any]) -> bool:
    availability = result.get("availability")
    return (
        (not filters.get("domain") or result.get("domain") == filters["domain"])
        and (
            filters.get("max_price_cents") is None
            or result.get("price_cents", 0) <= filters["max_price_cents"]
        )
        and (
            not filters.get("in_stock_only")
            or availability in {"in_stock", "low_stock"}
        )
        and all(
            result.get("attributes", {}).get(key) == value
            for key, value in filters.get("attributes", {}).items()
        )
    )


def validate_lab_1(base_url: str) -> list[str]:
    mission = _mission("retrieve")
    response = _search(base_url, mission)
    results = response.get("results") or []
    target = next(
        (
            item
            for item in results
            if item["product_id"] in mission["target_product_ids"]
        ),
        None,
    )
    _require(target is not None, "Lab 1 target is absent from the result window")
    signals = target.get("signals") or {}
    _require(
        (signals.get("trigram") or {}).get("rank") is not None,
        "Lab 1 target has no pg_trgm provenance",
    )
    _require(
        (signals.get("trigram") or {}).get("rrf_contribution") is not None,
        "Lab 1 target has no trigram RRF contribution",
    )
    _require(
        all(_eligible(item, mission["filters"]) for item in results),
        "Lab 1 returned a product that violates eligibility",
    )
    counts = (response.get("diagnostics") or {}).get("candidate_counts") or {}
    _require(counts.get("trigram_in_pool", 0) > 0, "Lab 1 trigram pool is empty")
    return [
        "expected retrieval anchor present",
        "trigram provenance present",
        "hard filters hold",
    ]


def _rrf_is_correct(result: dict[str, Any], rrf_k: int) -> bool:
    signals = result.get("signals") or {}
    expected = 0.0
    found = False
    for arm in ("fts", "trigram", "semantic"):
        signal = signals.get(arm) or {}
        rank = signal.get("rank")
        contribution = signal.get("rrf_contribution")
        if rank is None:
            continue
        found = True
        if contribution is None or abs(contribution - 1.0 / (rrf_k + rank)) > 1e-9:
            return False
        expected += contribution
    return found and abs(signals.get("rrf_score", 0.0) - expected) <= 1e-9


def validate_lab_2(base_url: str) -> list[str]:
    mission = _mission("rank")
    first = _search(base_url, mission)
    second = _search(base_url, mission)
    first_results = first.get("results") or []
    second_results = second.get("results") or []
    first_order = sorted(
        (
            item["signals"]["pre_rerank_rank"],
            item["product_id"],
        )
        for item in first_results
    )
    second_order = sorted(
        (
            item["signals"]["pre_rerank_rank"],
            item["product_id"],
        )
        for item in second_results
    )
    _require(first_order == second_order, "Lab 2 pre-rerank order is not repeatable")
    diagnostics = first.get("diagnostics") or {}
    profile = diagnostics.get("retrieval_profile") or {}
    rrf_k = profile.get("rrf_k")
    _require(isinstance(rrf_k, int), "Lab 2 response does not expose RRF k")
    _require(
        all(_rrf_is_correct(item, rrf_k) for item in first_results),
        "Lab 2 RRF contributions do not equal 1 / (k + source_rank)",
    )
    _require(
        diagnostics.get("rerank_status") == "applied",
        "Lab 2 Cohere Rerank was not applied",
    )
    target = next(
        (
            item
            for item in first_results
            if item["product_id"] in mission["target_product_ids"]
        ),
        None,
    )
    _require(target is not None, "Lab 2 target is absent from the result window")
    signals = target["signals"]
    _require(
        all(
            (signals.get(arm) or {}).get("rank") is not None
            for arm in ("fts", "trigram", "semantic")
        ),
        "Lab 2 target does not retain all candidate-arm ranks",
    )
    _require(
        signals.get("rerank_score") is not None,
        "Lab 2 target has no reranker score",
    )
    _require(
        all(
            (signals.get(arm) or {}).get("rank") == 1
            for arm in ("fts", "trigram", "semantic")
        ),
        "Lab 2 target does not rank first in every candidate arm",
    )
    _require(
        signals.get("pre_rerank_rank") == 1,
        "Lab 2 target is not fused rank 1 after the RRF repair",
    )
    _require(
        signals.get("final_rank") == 1,
        "Lab 2 target is not final rank 1 after bounded reranking",
    )
    return [
        "RRF arithmetic correct",
        "pre-rerank order repeatable",
        "reranking bounded and applied",
        "rank provenance present",
        "canonical winner is fused and final rank 1",
    ]


def _successful_steps(agent: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [
        step
        for step in agent.get("trace") or []
        if step.get("tool") == tool and step.get("outcome") == "success"
    ]


def _constraints_preserved(
    applied: dict[str, Any],
    required: dict[str, Any],
) -> bool:
    if required.get("domain") and applied.get("domain") != required["domain"]:
        return False
    if required.get("category_key") and (
        applied.get("category_key") != required["category_key"]
    ):
        return False
    if required.get("max_price_cents") is not None and (
        applied.get("max_price_cents") is None
        or applied["max_price_cents"] > required["max_price_cents"]
    ):
        return False
    if required.get("min_price_cents") is not None and (
        applied.get("min_price_cents") is None
        or applied["min_price_cents"] < required["min_price_cents"]
    ):
        return False
    if required.get("in_stock_only") and applied.get("in_stock_only") is not True:
        return False
    return all(
        (applied.get("attributes") or {}).get(key) == value
        for key, value in (required.get("attributes") or {}).items()
    )


def validate_agent_response(
    base_url: str,
    mission: dict[str, Any],
    agent: dict[str, Any],
) -> list[str]:
    searches = _successful_steps(agent, "search_products")
    _require(searches, "Lab 3 did not invoke search_products successfully")
    required_filters = mission["filters"]
    for step in searches:
        applied = (step.get("arguments") or {}).get("applied_filters") or {}
        _require(
            _constraints_preserved(applied, required_filters),
            "Lab 3 retrieval trace does not preserve structured constraints",
        )

    retrieval_runs = [
        _request(base_url, f"/api/retrieval/events/{step['retrieval_run_id']}")
        for step in searches
        if step.get("retrieval_run_id")
    ]
    considered = {
        candidate["product_id"]
        for run in retrieval_runs
        for candidate in run.get("candidates") or []
    }
    _require(
        considered.intersection(mission["target_product_ids"]),
        "Lab 3 retrieval runs considered none of the canonical targets",
    )

    recommendations = agent.get("recommendations") or []
    recommendation_ids = {item["product_id"] for item in recommendations}
    _require(len(recommendations) >= 2, "Lab 3 did not return a comparison shortlist")
    _require(
        all(_eligible(item, required_filters) for item in recommendations),
        "Lab 3 recommendation violates structured constraints",
    )
    _require(
        recommendation_ids <= considered,
        "Lab 3 recommended a product absent from persisted retrieval receipts",
    )

    comparisons = _successful_steps(agent, "compare_products")
    _require(comparisons, "Lab 3 did not invoke compare_products successfully")
    compared = {
        int(product_id)
        for step in comparisons
        for product_id in (step.get("arguments") or {}).get("product_ids", [])
    }
    _require(
        len(compared.intersection(recommendation_ids)) >= 2,
        "Lab 3 comparison does not cover the recommendation shortlist",
    )

    evidence_steps = _successful_steps(agent, "get_product_evidence")
    evidence_products = {
        int((step.get("arguments") or {})["product_id"])
        for step in evidence_steps
        if (step.get("arguments") or {}).get("product_id") is not None
    }
    _require(
        recommendation_ids <= evidence_products,
        "Lab 3 did not retrieve evidence for every recommended product",
    )
    _require(
        all((step.get("result_count") or 0) > 0 for step in evidence_steps),
        "Lab 3 evidence tool returned no evidence records",
    )

    explanations = _successful_steps(agent, "explain_retrieval")
    _require(
        len(explanations) == 1,
        "Lab 3 requires exactly one successful explain_retrieval tool call "
        f"before synthesis; found {len(explanations)}",
    )

    citations = agent.get("citations") or []
    _require(citations, "Lab 3 returned no citations")
    cited_product_ids = {int(citation["product_id"]) for citation in citations}
    _require(
        recommendation_ids <= cited_product_ids,
        "Lab 3 did not cite evidence for every recommended product",
    )
    resolved_evidence: list[dict[str, Any]] = []
    for citation in citations:
        evidence = _request(base_url, f"/api/evidence/{citation['evidence_id']}")
        _require(
            evidence["evidence_id"] == citation["evidence_id"]
            and evidence["product_id"] == citation["product_id"]
            and evidence["source_uri"] == citation["source_uri"]
            and evidence["revision"] == citation["revision"]
            and evidence["text"] == citation["quote"],
            f"Lab 3 citation {citation['number']} does not resolve exactly",
        )
        _require(
            citation["product_id"] in recommendation_ids,
            f"Lab 3 citation {citation['number']} belongs to an unselected product",
        )
        resolved_evidence.append({**evidence, **citation})

    for requirement in mission.get("required_citation_support", []):
        required_terms = [
            term.casefold().replace("_", " ").replace("-", " ")
            for term in requirement["all_terms"]
        ]
        matching = [
            item
            for item in resolved_evidence
            if item["product_id"] == requirement["product_id"]
            and item["evidence_type"] == requirement["evidence_type"]
            and all(
                term in item["text"].casefold().replace("_", " ").replace("-", " ")
                for term in required_terms
            )
        ]
        _require(
            bool(matching),
            "Lab 3 required citation support is absent for product "
            f"{requirement['product_id']}: evidence_type="
            f"{requirement['evidence_type']}, terms={requirement['all_terms']}",
        )

    return [
        "structured constraints preserved",
        "retrieval and comparison tools invoked",
        "evidence retrieved for every recommendation",
        "ranking explanation replayable",
        "citation IDs resolve exactly",
        "required claims supported",
    ]


def validate_lab_3(base_url: str) -> list[str]:
    checks: list[str] = []
    for mission in (_mission("reason"), _case("evidence-grounding")):
        agent = _request(
            base_url,
            "/api/agent/answer",
            {
                "question": mission["query"],
                "filters": mission["filters"],
                "result_limit": mission["top_k"],
            },
        )
        checks.extend(
            f"{mission['canonical_query_id']}: {check}"
            for check in validate_agent_response(base_url, mission, agent)
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    checks = {
        1: validate_lab_1,
        2: validate_lab_2,
        3: validate_lab_3,
    }[args.lab](args.api_url)
    for check in checks:
        print(f"PASS: {check}")
    print(f"Lab {args.lab}: production-path validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
