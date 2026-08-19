"""Measure the grounded Ask Mosaic path across Bedrock chat models.

This is a rehearsal tool, not an evaluation fixture. It uses the same Aurora
retrieval, evidence, citation validation, and Strands tool contract as the
Shop API. Retrieval is performed once to create stable synthesis input; each
model then receives exactly that product and evidence set before one full
grounded agent run is measured.

Usage:
    uv run python scripts/benchmark_ask_mosaic.py
    uv run python scripts/benchmark_ask_mosaic.py --runs 3 --full-runs 2
    uv run python scripts/benchmark_ask_mosaic.py \
        --agent-model global.anthropic.claude-haiku-4-5-20251001-v1:0 \
        --synthesis-model global.anthropic.claude-sonnet-4-6
    uv run python scripts/benchmark_ask_mosaic.py --output benchmarks/results/ask-mosaic.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Sonnet 5 and Opus 4.8 are not on Workshop Studio's enabled-model list, so this
# sweep only completes on an account with its own model access. Run
# `make check-model-access` first if a model here returns AccessDeniedException.
DEFAULT_MODELS = (
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-5",
    "global.anthropic.claude-opus-4-8",
)
DEFAULT_QUESTION = (
    "Find an ergonomic mesh chair for long workdays with adjustable lumbar "
    "support. Compare the strongest options and cite the evidence."
)
REQUIRED_TOOLS = {
    "search_products",
    "compare_products",
    "get_product_evidence",
    "synthesize_cited_answer",
}


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting an explicit environment."""
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _percentile(values: list[float], fraction: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min_ms": round(ordered[0], 1),
        "median_ms": round(statistics.median(ordered), 1),
        "p95_ms": round(_percentile(ordered, 0.95), 1),
    }


def _activate_models(agent_model_id: str, synthesis_model_id: str) -> None:
    """Set the model route while retaining the configured Aurora stack."""
    from service.config import get_settings

    # Keep the legacy setting in sync so a route can be copied into an existing
    # single-model deployment without also changing its fallback behavior.
    os.environ["BEDROCK_CHAT_MODEL_ID"] = agent_model_id
    os.environ["BEDROCK_AGENT_MODEL_ID"] = agent_model_id
    os.environ["BEDROCK_SYNTHESIS_MODEL_ID"] = synthesis_model_id
    get_settings.cache_clear()


def _controlled_context(question: str, result_limit: int):
    """Retrieve one stable product/evidence set for a fair synthesis comparison."""
    from service.catalog import get_product_evidence_records
    from service.models import SearchFilters, SearchRequest
    from service.retrieval import get_retrieval_service

    retrieval_service = get_retrieval_service()
    result = retrieval_service.search(
        SearchRequest(
            query=question,
            filters=SearchFilters(),
            # Product specifications are source-addressable for the full corpus,
            # so this benchmark preserves the served retrieval order rather than
            # selecting a different evidence-backed subset.
            limit=result_limit,
            include_diagnostics=True,
            rerank=True,
            session_id="ask-mosaic-model-benchmark",
        )
    )
    products = []
    evidence = []
    evidence_query_embedding = retrieval_service.embed_query(question)
    for candidate in result.results:
        records = get_product_evidence_records(
            candidate.product_id,
            question,
            evidence_query_embedding,
            limit=3,
        )
        if not records:
            raise RuntimeError(
                "Controlled benchmark found no source-addressable evidence for "
                f"retrieved product {candidate.product_id}"
            )
        products.append(candidate)
        evidence.extend(records)
        if len(products) == result_limit:
            break
    if len(products) != result_limit:
        raise RuntimeError(
            f"Controlled benchmark found only {len(products)} products in "
            f"{len(result.results)} retrieved candidates; expected {result_limit}."
        )
    return result, products, evidence, []


def _measure_synthesis(
    agent_model_id: str,
    synthesis_model_id: str,
    question: str,
    products: list[Any],
    evidence: list[Any],
    runs: int,
) -> dict[str, Any]:
    from service.config import get_settings
    from service.synthesis import synthesize_cited_answer

    times: list[float] = []
    attempts: list[int] = []
    citation_counts: list[int] = []
    failures: list[str] = []
    for _ in range(runs):
        _activate_models(agent_model_id, synthesis_model_id)
        started = perf_counter()
        try:
            _, citations, usage = synthesize_cited_answer(
                question,
                products,
                evidence,
                settings=get_settings(),
            )
        # A benchmark run records any provider or orchestration failure and
        # continues so one model cannot suppress results for the others.
        except Exception as error:  # noqa: BLE001
            failures.append(f"{type(error).__name__}: {error}")
            continue
        times.append((perf_counter() - started) * 1_000)
        attempts.append(int(usage.get("attempts", 0)))
        citation_counts.append(len(citations))
    return {
        "runs": runs,
        "successes": len(times),
        "failures": failures,
        "latency": _summary(times) if times else None,
        "repair_attempts": attempts,
        "citation_counts": citation_counts,
    }


def _measure_full_agent(
    agent_model_id: str,
    synthesis_model_id: str,
    question: str,
    result_limit: int,
    runs: int,
    expected_product_ids: set[int],
) -> dict[str, Any]:
    from service.agent import ProductDiscoveryAgent
    from service.models import AgentRequest, SearchFilters

    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for _ in range(runs):
        _activate_models(agent_model_id, synthesis_model_id)
        started = perf_counter()
        try:
            response = ProductDiscoveryAgent().answer(
                AgentRequest(
                    question=question,
                    filters=SearchFilters(),
                    result_limit=result_limit,
                )
            )
        # The full agent boundary includes third-party model and tool plugins
        # whose exception hierarchies are not under this repository's control.
        except Exception as error:  # noqa: BLE001
            failures.append(f"{type(error).__name__}: {error}")
            continue
        total_ms = (perf_counter() - started) * 1_000
        tools = [step.tool for step in response.trace]
        successful_tools = {
            step.tool for step in response.trace if step.outcome == "success"
        }
        failed_tool_names = [
            step.tool for step in response.trace if step.outcome != "success"
        ]
        tool_ms = sum(step.latency_ms or 0 for step in response.trace)
        recommendation_ids = [
            product.product_id for product in response.recommendations
        ]
        cited_product_ids = sorted(
            {citation.product_id for citation in response.citations}
        )
        records.append(
            {
                "total_ms": round(total_ms, 1),
                "tool_ms": round(tool_ms, 1),
                "model_and_orchestration_ms": round(max(total_ms - tool_ms, 0), 1),
                "tool_names": tools,
                "tool_outcomes": [
                    {"tool": step.tool, "outcome": step.outcome}
                    for step in response.trace
                ],
                "required_successful_tools_present": sorted(
                    REQUIRED_TOOLS.intersection(successful_tools)
                ),
                "grounded_workflow": REQUIRED_TOOLS.issubset(successful_tools),
                "clean_workflow": not failed_tool_names,
                "failed_tool_names": failed_tool_names,
                "recommendation_count": len(response.recommendations),
                "recommendation_ids": recommendation_ids,
                "citation_product_ids": cited_product_ids,
                "plan_queries": [step.query for step in response.plan],
                "expected_products_present": (
                    sorted(expected_product_ids.intersection(recommendation_ids))
                    if expected_product_ids
                    else []
                ),
                "expected_products_covered": (
                    expected_product_ids.issubset(recommendation_ids)
                    if expected_product_ids
                    else None
                ),
                "citation_count": len(response.citations),
            }
        )
    totals = [record["total_ms"] for record in records]
    return {
        "runs": runs,
        "successes": len(records),
        "failures": failures,
        "latency": _summary(totals) if totals else None,
        "records": records,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure citation-bounded synthesis with deterministic claim checks "
            "and the full Ask Mosaic "
            "workflow against the configured Aurora database."
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help="Bedrock inference-profile IDs to compare.",
    )
    parser.add_argument(
        "--agent-model",
        help=(
            "Model for Strands planning and tool orchestration. Supply with "
            "--synthesis-model to benchmark a split route."
        ),
    )
    parser.add_argument(
        "--synthesis-model",
        help=(
            "Model for citation-bounded answer synthesis. Supply with "
            "--agent-model to benchmark a split route."
        ),
    )
    parser.add_argument("--runs", type=int, default=2, help="Synthesis runs/model.")
    parser.add_argument(
        "--full-runs",
        type=int,
        default=1,
        help="Full agent runs/model. Each run writes normal audit events to Aurora.",
    )
    parser.add_argument("--result-limit", type=int, default=3)
    parser.add_argument(
        "--expected-product-id",
        action="append",
        type=int,
        default=[],
        help=(
            "Product ID that the route must recommend. Repeat the flag for "
            "multi-product fixtures."
        ),
    )
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Optional local configuration file; explicit environment wins.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report to this path in addition to stdout.",
    )
    args = parser.parse_args()
    if args.runs < 1 or args.full_runs < 0:
        parser.error("--runs must be at least 1 and --full-runs cannot be negative")
    if not 1 <= args.result_limit <= 6:
        parser.error("--result-limit must be between 1 and 6")
    if bool(args.agent_model) != bool(args.synthesis_model):
        parser.error("--agent-model and --synthesis-model must be supplied together")
    if args.agent_model and args.models != list(DEFAULT_MODELS):
        parser.error(
            "--models cannot be combined with a split route; use either "
            "--models or --agent-model with --synthesis-model"
        )
    return args


def main() -> int:
    args = _parse_args()
    _load_env_file(args.env_file)
    if not os.getenv("DATABASE_URL"):
        print(
            "DATABASE_URL is not set. Ask Mosaic benchmarking requires the "
            "Aurora workshop cluster.",
            file=sys.stderr,
        )
        return 2
    routes = (
        [
            {
                "label": (f"agent={args.agent_model};synthesis={args.synthesis_model}"),
                "agent_model_id": args.agent_model,
                "synthesis_model_id": args.synthesis_model,
            }
        ]
        if args.agent_model
        else [
            {
                "label": model_id,
                "agent_model_id": model_id,
                "synthesis_model_id": model_id,
            }
            for model_id in args.models
        ]
    )
    _activate_models(
        routes[0]["agent_model_id"],
        routes[0]["synthesis_model_id"],
    )

    retrieval, products, evidence, skipped_without_evidence = _controlled_context(
        args.question,
        args.result_limit,
    )
    report: dict[str, Any] = {
        "question": args.question,
        "controlled_retrieval": {
            "search_event_id": str(retrieval.search_event_id),
            "product_ids": [product.product_id for product in products],
            "product_titles": [product.title for product in products],
            "evidence_count": len(evidence),
            "skipped_without_evidence": skipped_without_evidence,
            "latency_ms": (
                retrieval.diagnostics.total_latency_ms
                if retrieval.diagnostics is not None
                else None
            ),
        },
        "routes": {},
        "notes": [
            "Synthesis uses identical retrieved products and evidence for every model.",
            "Full agent runs use the normal read-only tool contract and write normal audit rows.",
            "model_and_orchestration_ms is total request time minus measured tool time; it is not a Bedrock service metric.",
        ],
    }
    for route in routes:
        print(f"Benchmarking {route['label']}...", file=sys.stderr, flush=True)
        report["routes"][route["label"]] = {
            "agent_model_id": route["agent_model_id"],
            "synthesis_model_id": route["synthesis_model_id"],
            "synthesis": _measure_synthesis(
                route["agent_model_id"],
                route["synthesis_model_id"],
                args.question,
                products,
                evidence,
                args.runs,
            ),
            "full_agent": (
                _measure_full_agent(
                    route["agent_model_id"],
                    route["synthesis_model_id"],
                    args.question,
                    args.result_limit,
                    args.full_runs,
                    set(args.expected_product_id),
                )
                if args.full_runs
                else None
            ),
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
