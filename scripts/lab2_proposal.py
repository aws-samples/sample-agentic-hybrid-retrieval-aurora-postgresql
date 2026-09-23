"""Grade a Lab 2 proposal: one retrieval setting, judged on real shopper queries.

The participant changes one setting, states in advance what result would justify
adopting it, and decides to adopt or reject it. This module measures the change
over 141 ESCI queries whose judged products are in the catalog, and over four
reviewed chair controls reported separately, then checks that the decision
follows from the participant's own criterion. Adopting and rejecting are both
passable; a decision that contradicts its own stated rule is not.

The search lists come from `data/evals/lab2_search_cache.json`. Before using it,
the grader checks the cache against the live catalog and search functions, and
reruns three queries live, timing them at the baseline and proposed limits. The
reranking model is not called, so latency here is retrieval and fusion latency,
not end-to-end latency.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from scripts.cache_lab2_arms import (
    MAX_LIMITS,
    decode_vector,
    search_identity,
    search_lists,
)

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data/evals/lab2_search_cache.json"
SUBSET = REPO / "data/evals/esci_judged_subset.json"
VECTORS = REPO / "data/evals/esci_query_vectors.json"
RERANK_LATENCY = REPO / "data/evals/rerank_latency.json"
PROPOSAL_WORK = Path(".local/lab-2/proposal.json")
GAINS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
MAX_RERANK_PRODUCTS = 100
PRODUCTS_PER_SEARCH_UNIT = 100
SETTINGS = {
    "rrf_k": (1, 1000),
    "fused_limit": (10, MAX_RERANK_PRODUCTS),
    "fts_limit": (1, MAX_LIMITS["fts"]),
    "trigram_limit": (1, MAX_LIMITS["trigram"]),
    "semantic_limit": (1, MAX_LIMITS["vector"]),
}
ARM_OF = {"fts_limit": "fts", "trigram_limit": "trigram", "semantic_limit": "vector"}
SPOT_CHECKS = 3


class ProposalError(ValueError):
    """The proposal cannot be graded as written."""


def validate(proposal: dict[str, Any]) -> tuple[str, int]:
    """Return the one changed setting and its value, or explain the problem."""
    change = proposal.get("change")
    if not isinstance(change, dict) or len(change) != 1:
        raise ProposalError(
            'change must name exactly one setting: {"change": {"<setting>": <integer>}}'
        )
    ((setting, value),) = change.items()
    if setting not in SETTINGS or not isinstance(value, int):
        raise ProposalError(f"change one of {sorted(SETTINGS)} to an integer")
    low, high = SETTINGS[setting]
    if not low <= value <= high:
        raise ProposalError(
            f"{setting}={value} is outside the budget {low}..{high}; "
            f"the reranker budget is {MAX_RERANK_PRODUCTS} products, one billed "
            "search unit per query"
        )
    criterion = proposal.get("criterion")
    if not isinstance(criterion, dict) or not {
        "min_exact_gain",
        "max_queries_worse",
    } <= set(criterion):
        raise ProposalError(
            "criterion must state min_exact_gain and max_queries_worse before you "
            "see the result"
        )
    if proposal.get("decision") not in {"adopt", "reject"}:
        raise ProposalError('decision must be "adopt" or "reject"')
    if not str(proposal.get("reason", "")).strip():
        raise ProposalError("reason must explain the decision in your own words")
    return setting, value


def fuse(lists: dict[str, list], k: int, limits: dict[str, int]) -> list[int]:
    scores: dict[int, float] = {}
    for arm, rows in lists.items():
        for product_id, rank in rows:
            if rank <= limits[arm]:
                scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
    return [pid for pid, _ in sorted(scores.items(), key=lambda i: (-i[1], i[0]))]


def condensed_ndcg(order: list[int], labels: dict[int, str]) -> float:
    judged = [labels[pid] for pid in order if pid in labels][:10]
    ideal = sorted((GAINS[label] for label in labels.values()), reverse=True)[:10]
    dcg = sum(GAINS[label] / math.log2(i + 2) for i, label in enumerate(judged))
    best = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal))
    return dcg / best if best else 0.0


def settings_for(baseline: dict[str, int], setting: str | None, value: int | None):
    chosen = dict(baseline)
    if setting:
        chosen[setting] = value
    limits = {arm: chosen[key] for key, arm in ARM_OF.items()}
    return chosen, limits


def measure(cache: dict, subset: dict, chosen: dict, limits: dict) -> dict:
    per_query = {}
    for case in subset["queries"]:
        order = fuse(cache["queries"][str(case["query_id"])], chosen["rrf_k"], limits)
        labels = {j["product_id"]: j["esci_label"] for j in case["judgments"]}
        exact = {pid for pid, label in labels.items() if label == "E"}
        per_query[case["query_id"]] = {
            "category": case["filters"]["category_key"],
            "exact_in_cutoff": len(exact & set(order[: chosen["fused_limit"]])),
            "ndcg": condensed_ndcg(order, labels),
        }
    chairs = []
    for control in cache["chair_controls"]:
        order = fuse(control["lists"], chosen["rrf_k"], limits)
        position = (
            order.index(control["target"]) + 1 if control["target"] in order else None
        )
        chairs.append(
            {
                "id": control["id"],
                "query": control["query"],
                "target_position": position,
                "reaches_reranking": position is not None
                and position <= chosen["fused_limit"],
            }
        )
    return {"per_query": per_query, "chair_controls": chairs}


def sign_test(better: int, worse: int) -> float:
    total = better + worse
    if not total:
        return 1.0
    tail = sum(math.comb(total, i) for i in range(min(better, worse) + 1))
    return min(1.0, 2 * tail / 2**total)


def compare(base: dict, proposed: dict) -> dict:
    rows = [(base["per_query"][q], proposed["per_query"][q]) for q in base["per_query"]]
    better = sum(p["exact_in_cutoff"] > b["exact_in_cutoff"] for b, p in rows)
    worse = sum(p["exact_in_cutoff"] < b["exact_in_cutoff"] for b, p in rows)
    categories: dict[str, list[int]] = {}
    for b, p in rows:
        pair = categories.setdefault(b["category"], [0, 0, 0])
        pair[0] += b["exact_in_cutoff"]
        pair[1] += p["exact_in_cutoff"]
        pair[2] += int(p["exact_in_cutoff"] < b["exact_in_cutoff"])
    return {
        "exact_in_cutoff": {
            "baseline": sum(b["exact_in_cutoff"] for b, _ in rows),
            "proposed": sum(p["exact_in_cutoff"] for _, p in rows),
        },
        "queries_better": better,
        "queries_worse": worse,
        "sign_test_p": round(sign_test(better, worse), 4),
        "mean_condensed_ndcg10": {
            "baseline": round(statistics.fmean(b["ndcg"] for b, _ in rows), 4),
            "proposed": round(statistics.fmean(p["ndcg"] for _, p in rows), 4),
        },
        "ndcg_queries_worse": sum(p["ndcg"] < b["ndcg"] - 1e-12 for b, p in rows),
        "by_category": {
            name: {"baseline": v[0], "proposed": v[1], "queries_worse": v[2]}
            for name, v in sorted(categories.items())
        },
    }


def verify_cache(
    connection, cache: dict, subset: dict, limits: dict, base_limits: dict
) -> dict:
    """Refuse a stale cache; rerun a few queries live and time both settings."""
    identity = search_identity(connection)
    for key, live in identity.items():
        if cache[key] != live:
            raise ProposalError(
                f"cached search lists were built for {key} {cache[key][:12]}, but "
                f"Aurora has {live[:12]}; rebuild with scripts/cache_lab2_arms.py"
            )
    vectors = json.loads(VECTORS.read_text())["vectors"]
    for case in subset["queries"][:SPOT_CHECKS]:
        vector = decode_vector(vectors[str(case["query_id"])])
        live = search_lists(connection, case["query"], case["filters"], vector)
        if live != cache["queries"][str(case["query_id"])]:
            raise ProposalError(
                f"live search lists for query {case['query_id']} differ from the "
                "cache; rebuild it with scripts/cache_lab2_arms.py"
            )
    if limits == base_limits:
        return {
            "live_spot_checks": SPOT_CHECKS,
            "retrieval_fusion_ms_median": "unchanged: the proposal runs the same "
            "retrieval SQL, so any timing difference would be noise",
        }
    timings = {
        "baseline_ms": _timed(connection, subset, vectors, base_limits, cache),
        "proposed_ms": _timed(connection, subset, vectors, limits, cache),
    }
    return {
        "live_spot_checks": SPOT_CHECKS,
        "retrieval_fusion_ms_median": {
            name: round(statistics.median(values), 1)
            for name, values in timings.items()
        },
    }


def _timed(
    connection, subset: dict, vectors: dict, limits: dict, cache: dict
) -> list[float]:
    """Wall time of the installed fused search at the given method limits."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    samples = []
    for case in subset["queries"][:SPOT_CHECKS]:
        started = time.perf_counter()
        connection.execute(
            f"SELECT count(*) FROM {schema}.search_hybrid_rrf(%s, %s::vector, "
            "%s::jsonb, fts_limit => %s, trigram_limit => %s, semantic_limit => %s, "
            "trigram_threshold => %s::real)",
            (
                case["query"],
                decode_vector(vectors[str(case["query_id"])]),
                json.dumps(case["filters"]),
                limits["fts"],
                limits["trigram"],
                limits["vector"],
                cache["trigram_threshold"],
            ),
        ).fetchone()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def expected_decision(comparison: dict, criterion: dict) -> str:
    gain = (
        comparison["exact_in_cutoff"]["proposed"]
        - comparison["exact_in_cutoff"]["baseline"]
    )
    adopt = (
        gain >= criterion["min_exact_gain"]
        and comparison["queries_worse"] <= criterion["max_queries_worse"]
    )
    return "adopt" if adopt else "reject"


def grade(proposal: dict[str, Any], connection, baseline: dict[str, int]) -> dict:
    """Measure the proposal and check the decision against its own criterion."""
    setting, value = validate(proposal)
    cache = json.loads(CACHE.read_text())
    subset = json.loads(SUBSET.read_text())
    base_settings, base_limits = settings_for(baseline, None, None)
    chosen, limits = settings_for(baseline, setting, value)
    comparison = compare(
        measure(cache, subset, base_settings, base_limits),
        measure(cache, subset, chosen, limits),
    )
    chairs = {
        "baseline": measure(cache, subset, base_settings, base_limits)[
            "chair_controls"
        ],
        "proposed": measure(cache, subset, chosen, limits)["chair_controls"],
    }
    live = verify_cache(connection, cache, subset, limits, base_limits)
    expected = expected_decision(comparison, proposal["criterion"])
    failures = []
    if proposal["decision"] != expected:
        failures.append(
            f"your criterion says {expected}, but you chose {proposal['decision']}; "
            "either follow your rule or change the rule and explain why"
        )
    rerank = json.loads(RERANK_LATENCY.read_text()) if RERANK_LATENCY.exists() else None
    return {
        "change": {setting: value},
        "comparison": comparison,
        "chair_controls": chairs,
        "work": {
            "products_to_reranker": {
                "baseline": base_settings["fused_limit"],
                "proposed": chosen["fused_limit"],
            },
            "billed_search_units_per_query": {
                "baseline": math.ceil(
                    base_settings["fused_limit"] / PRODUCTS_PER_SEARCH_UNIT
                ),
                "proposed": math.ceil(chosen["fused_limit"] / PRODUCTS_PER_SEARCH_UNIT),
            },
            **live,
            "measured_rerank_latency_reference": rerank,
        },
        "expected_decision": expected,
        "decision": {
            k: proposal[k] for k in ("change", "criterion", "decision", "reason")
        },
        "scope": (
            "141 ESCI queries whose judged products are in this catalog (82 headphones, "
            "58 monitor, 1 chair); unjudged products count as unknown. Chair controls "
            "are four reviewed requests, not relevance judgments. Latency is "
            "retrieval and fusion only; the reranking model is not called."
        ),
        "failures": failures,
    }
