"""Exercise the participant's registered tool against Mosaic's real API."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
from strands.tools.registry import ToolRegistry

from service.models import SearchResponse

ROOT = Path(__file__).resolve().parents[1]


class BuilderCheckError(RuntimeError):
    pass


def require(condition: bool, found: Any, fix: str) -> None:
    if not condition:
        raise BuilderCheckError(f"Build check failed: found {found!r}; fix: {fix}")


def load_example(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("mosaic_participant_tool", path)
    if spec is None or spec.loader is None:
        raise BuilderCheckError(
            f"Cannot load {path}; fix: pass the Python file created with --starter"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_tool(
    module: ModuleType, budgets: list[int], query: str
) -> list[dict[str, Any]]:
    """Run the registered callable and replay the service's own saved responses."""
    require(
        len(set(budgets)) >= 2,
        budgets,
        "provide at least two distinct budgets so the caller's constraint is exercised",
    )
    registry = ToolRegistry()
    registry.process_tools(module.registered_tools())
    tools = registry.registry
    require(
        "search_call_headphones" in tools,
        list(tools),
        "return [search_call_headphones] from registered_tools",
    )
    registered = tools["search_call_headphones"]
    require(
        registered is module.search_call_headphones,
        registered.tool_name,
        "register the tool implemented in this exercise",
    )
    reports = []
    endpoint = os.environ.get("MOSAIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
    for budget in budgets:
        # The same decorated callable the agent invokes, never a second search implementation.
        response = SearchResponse.model_validate(
            registered(query=query, max_price_cents=budget)
        )
        receipt = httpx.get(
            f"{endpoint}/api/retrieval/events/{response.search_event_id}/response",
            timeout=90,
        )
        receipt.raise_for_status()
        saved = SearchResponse.model_validate(receipt.json())
        require(
            saved.query == query, saved.query, "forward the shopper query unchanged"
        )
        filters = saved.applied_filters
        for key, expected in {
            "category_key": "over-ear-headphones",
            "in_stock_only": True,
            "max_price_cents": budget,
            "attributes": {"microphone": True},
        }.items():
            require(
                filters.get(key) == expected,
                {key: filters.get(key)},
                f"set {key} to {expected!r} in call_filters",
            )
        require(
            bool(saved.results),
            len(saved.results),
            "use the Clearer calls request with a budget that has available products",
        )
        require(
            [p.product_id for p in response.results]
            == [p.product_id for p in saved.results],
            "returned products differ from the saved search",
            "return the API response without inserting or removing products",
        )
        for product in saved.results:
            require(
                product.category_key == "over-ear-headphones"
                and product.attributes.get("microphone") is True
                and product.price_cents <= budget
                and product.availability in {"in_stock", "low_stock"},
                product.product_id,
                "keep category, microphone, availability and budget in the SQL filter request",
            )
        reports.append(
            {
                "budget_cents": budget,
                "products_checked": len(saved.results),
                "search_event_id": str(saved.search_event_id),
                "playground": f"/labs/retrieval?event={saved.search_event_id}",
            }
        )
    require(
        len({item["search_event_id"] for item in reports}) == len(budgets),
        reports,
        "issue a fresh search for each budget",
    )
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--budgets", nargs="+", type=int, default=[20000, 10000])
    args = parser.parse_args()
    if args.api_url:
        os.environ["MOSAIC_API_URL"] = args.api_url
    request = next(
        item
        for item in json.loads(
            (ROOT / "data/evals/mosaic_labs_missions.json").read_text()
        )["playground"]["requests"]
        if item["id"] == "clear-calls"
    )
    try:
        reports = check_tool(load_example(args.module), args.budgets, request["query"])
    except (
        BuilderCheckError,
        NotImplementedError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps({"status": "passed", "runs": reports}, indent=2))


if __name__ == "__main__":
    main()
