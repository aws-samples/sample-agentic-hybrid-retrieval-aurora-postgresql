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


def call_filters(max_price_cents: int) -> SearchFilters:
    """Require available over-ear headphones with a microphone, within budget."""
    if (
        isinstance(max_price_cents, bool)
        or not isinstance(max_price_cents, int)
        or max_price_cents <= 0
    ):
        raise ValueError(
            f"max_price_cents is {max_price_cents!r}; use a positive integer amount in cents"
        )
    # BUILD_FILTERS_START
    return SearchFilters(
        category_key="over-ear-headphones",
        in_stock_only=True,
        max_price_cents=max_price_cents,
        attributes={"microphone": True},
    )
    # BUILD_FILTERS_END


@tool
def search_call_headphones(query: str, max_price_cents: int) -> dict[str, Any]:
    """Find available headphones with a microphone within the shopper's budget.

    Args:
        query: The shopper's request, including preferences to rank by.
        max_price_cents: The shopper's maximum price, in integer cents.

    Returns:
        Ranked products, applied filters, diagnostics and a saved search ID.
        A microphone filter proves its presence, not its noise suppression.
    """
    request = SearchRequest(query=query, filters=call_filters(max_price_cents))
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
            "Use search_call_headphones once for the user's request and exact budget. "
            "In at most 120 words, report only the first three returned product titles "
            "and prices, plus the complete search_event_id. Do not list the remaining products. "
            "Do not invent specifications or claim microphone quality from presence alone. "
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
    parser.add_argument("--max-price-cents", type=int)
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
    if not args.query or args.max_price_cents is None:
        parser.error("provide --query and --max-price-cents, or use --starter")
    # Validate before invoking a model so an invalid budget makes no model call.
    call_filters(args.max_price_cents)
    if args.agent:
        create_agent()(
            f"Request: {args.query}\nMaximum price in cents: {args.max_price_cents}"
        )
    else:
        print(
            json.dumps(
                search_call_headphones(args.query, args.max_price_cents), indent=2
            )
        )


if __name__ == "__main__":
    main()
