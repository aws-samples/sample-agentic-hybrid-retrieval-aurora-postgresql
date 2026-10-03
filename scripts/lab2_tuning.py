"""Measure Lab 2's tuning choices on real shopper queries.

After repairing fusion, a participant reads what three retrieval changes would do,
derived from the served profile: a reranking shortlist half again as long, and the
fusion constant doubled and halved. Each is measured over 141 ESCI queries whose
judged products are in the catalog, and over four reviewed chair controls reported
separately. The participant decides what they would ship; nothing here grades that
decision.

The search lists come from the cache bootstrap prepared on this workshop's own
Aurora indexes, or the published reference cache outside a workshop. Before
using it, the comparison checks the source, catalog, functions and HNSW settings,
then reruns three queries live. The reranking model is not called.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from scripts.cache_lab2_arms import (
    cache_path,
    cache_source_sha256,
    decode_vector,
    search_identity,
    search_lists,
)

REPO = Path(__file__).resolve().parents[1]
SUBSET = REPO / "data/evals/esci_judged_subset.json"
VECTORS = REPO / "data/evals/esci_query_vectors.json"
GAINS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
MAX_RERANK_PRODUCTS = 100
PRODUCTS_PER_SEARCH_UNIT = 100
ARM_OF = {"fts_limit": "fts", "trigram_limit": "trigram", "semantic_limit": "vector"}
SPOT_CHECKS = 3


class TuningError(ValueError):
    """The comparison cannot be measured as configured."""


def candidates(baseline: dict[str, int]) -> list[tuple[str, str, int]]:
    """Three changes derived from the served profile, so no setting is restated here."""
    longer = min(MAX_RERANK_PRODUCTS, round(baseline["fused_limit"] * 3 / 2))
    doubled, halved = baseline["rrf_k"] * 2, max(1, baseline["rrf_k"] // 2)
    return [
        (f"Shortlist of {longer}", "fused_limit", longer),
        (f"k = {doubled}", "rrf_k", doubled),
        (f"k = {halved}", "rrf_k", halved),
    ]


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


def verify_cache(connection, cache: dict, subset: dict) -> dict:
    """Refuse a stale cache, then rerun a few queries live against it."""
    expected_source = cache_source_sha256()
    if cache.get("source_sha256") != expected_source:
        raise TuningError(
            f"cached source_sha256={cache.get('source_sha256')!r}, expected "
            f"{expected_source}; the bundled search cache is out of date. "
            "Ask the facilitator to rebuild it with scripts/cache_lab2_arms.py --for-workshop "
            "against this release's Aurora database."
        )
    identity = search_identity(connection)
    for key, live in identity.items():
        if cache.get(key) != live:
            raise TuningError(
                f"cached search lists have {key}={cache.get(key)!r}, but "
                f"Aurora expects {live}; ask the facilitator to rebuild with "
                "scripts/cache_lab2_arms.py --for-workshop"
            )
    vectors = json.loads(VECTORS.read_text())["vectors"]
    for case in subset["queries"][:SPOT_CHECKS]:
        vector = decode_vector(vectors[str(case["query_id"])])
        live = search_lists(connection, case["query"], case["filters"], vector)
        if live != cache["queries"][str(case["query_id"])]:
            raise TuningError(
                f"live search lists for query {case['query_id']} differ from the "
                "cache; ask the facilitator to rebuild it with "
                "scripts/cache_lab2_arms.py --for-workshop"
            )
    return {"live_spot_checks": SPOT_CHECKS}


def comparison_table(connection, baseline: dict[str, int]) -> dict[str, Any]:
    """Measure each derived change against the served profile on the judged queries."""
    cache = json.loads(cache_path(REPO).read_text())
    subset = json.loads(SUBSET.read_text())
    base_settings, base_limits = settings_for(baseline, None, None)
    live = verify_cache(connection, cache, subset)
    base = measure(cache, subset, base_settings, base_limits)
    rows = []
    for label, setting, value in candidates(baseline):
        chosen, limits = settings_for(baseline, setting, value)
        proposed = measure(cache, subset, chosen, limits)
        comparison = compare(base, proposed)
        rows.append(
            {
                "label": label,
                "change": {setting: value},
                "exact_gain": comparison["exact_in_cutoff"]["proposed"]
                - comparison["exact_in_cutoff"]["baseline"],
                "queries_better": comparison["queries_better"],
                "queries_worse": comparison["queries_worse"],
                "sign_test_p": comparison["sign_test_p"],
                "chair_controls_moved": [
                    {
                        "id": b["id"],
                        "from": b["target_position"],
                        "to": p["target_position"],
                    }
                    for b, p in zip(
                        base["chair_controls"], proposed["chair_controls"], strict=True
                    )
                    if b["target_position"] != p["target_position"]
                ],
                "billed_search_units_per_query": math.ceil(
                    chosen["fused_limit"] / PRODUCTS_PER_SEARCH_UNIT
                ),
            }
        )
    return {
        "baseline": {
            "exact_in_cutoff": sum(
                q["exact_in_cutoff"] for q in base["per_query"].values()
            ),
            "billed_search_units_per_query": math.ceil(
                base_settings["fused_limit"] / PRODUCTS_PER_SEARCH_UNIT
            ),
        },
        "rows": rows,
        "live": live,
        "scope": (
            "141 ESCI queries whose judged products are in this catalog (82 headphones, "
            "58 monitor, 1 chair); unjudged products count as unknown. Chair controls "
            "are four reviewed requests, not relevance judgments. The reranking model "
            "is not called."
        ),
    }
