"""Build a filtered search tool over Mosaic's existing Aurora-backed API.

Run from a Mosaic checkout. The HTTP service owns retrieval, reranking and the
saved search record; this example owns the shopper's eligibility rule.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
from strands import Agent, tool
from strands.models import BedrockModel

from service.config import get_settings
from service.models import SearchFilters, SearchRequest, SearchResponse


def call_filters(brand: str) -> SearchFilters:
    """Keep headphone searches within the brand chosen by the caller."""
    if not isinstance(brand, str) or not brand.strip():
        raise ValueError(
            f"brand is {brand!r}; use a nonempty catalog brand, such as Bose or Sony"
        )
    # BUILD_FILTERS_START
    return SearchFilters(
        domain="consumer_electronics",
        category_key="headphones",
        brand=brand.strip(),
    )
    # BUILD_FILTERS_END


@tool
def search_call_headphones(query: str, brand: str) -> dict[str, Any]:
    """Find headphones from the requested brand using the real catalog.

    Args:
        query: The shopper's request, including preferences to rank by.
        brand: The catalog brand the shopper wants to consider.

    Returns:
        Ranked products, applied filters, diagnostics and a saved search ID.
        Product claims still require supporting records; stock is not known.
    """
    request = SearchRequest(query=query, filters=call_filters(brand))
    endpoint = os.environ.get("MOSAIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
    response = httpx.post(
        f"{endpoint}/api/search",
        json=request.model_dump(mode="json"),
        timeout=90,
    )
    response.raise_for_status()
    return SearchResponse.model_validate(response.json()).model_dump(mode="json")


def registered_tools() -> list[Any]:
    """The exact tool list passed to the example agent."""
    # BUILD_TOOLS_START
    return [search_call_headphones]
    # BUILD_TOOLS_END


def create_agent() -> Agent:
    """Reuse Mosaic's configured Bedrock model without creating AWS resources."""
    settings = get_settings()
    if not settings.agent_model_id:
        raise ValueError(
            "No agent model configured; load the Mosaic environment before using --agent"
        )
    return Agent(
        model=BedrockModel(
            model_id=settings.agent_model_id,
            region_name=settings.aws_region,
            max_tokens=1000,
        ),
        tools=registered_tools(),
        system_prompt=(
            "Use search_call_headphones once for the user's request and chosen brand. "
            "In at most 120 words, report only the first three returned product titles "
            "plus the complete search_event_id. Do not list the remaining products. "
            "Do not invent specifications, current prices, stock or microphone quality. "
            "This exercise returns a shortlist; cited answers use Mosaic's evidence tools."
        ),
    )


def write_starter(destination: Path) -> None:
    """Generate the two participant edit points from the working reference."""
    source = Path(__file__).read_text()
    for section, replacement in [
        (
            "FILTERS",
            '    raise NotImplementedError("Build the SearchFilters for Alex’s call headphones.")\n',
        ),
        ("TOOLS", "    return []\n"),
    ]:
        start = source.index(f"    # BUILD_{section}_START\n") + len(
            f"    # BUILD_{section}_START\n"
        )
        end = source.index(f"    # BUILD_{section}_END", start)
        source = source[:start] + replacement + source[end:]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as output:
        output.write(source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--starter",
        type=Path,
        help="Write a new participant file; existing files are never overwritten",
    )
    parser.add_argument("--query")
    parser.add_argument("--brand")
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Let the configured Bedrock agent call the tool",
    )
    args = parser.parse_args()
    if args.starter:
        write_starter(args.starter)
        print(f"Created {args.starter}. Implement call_filters and registered_tools.")
        return
    if not args.query or args.brand is None:
        parser.error("provide --query and --brand, or use --starter")
    call_filters(args.brand)
    if args.agent:
        create_agent()(f"Request: {args.query}\nRequired brand: {args.brand}")
    else:
        print(json.dumps(search_call_headphones(args.query, args.brand), indent=2))


if __name__ == "__main__":
    main()
