"""Stateless MCP 2026-07-28 tools over the catalog FastAPI service."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.models import (  # noqa: E402
    Availability,
    Domain,
    ProductDetail,
    RetrievalRunResponse,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)

from catalog_mcp.api import get_api_client  # noqa: E402

READ_ONLY_QUERY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
READ_ONLY_LOOKUP = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

mcp = MCPServer(
    name="mosaic-retrieval",
    title="Mosaic hybrid product retrieval",
    description=(
        "Read-only product discovery through PostgreSQL full-text, pg_trgm, "
        "pgvector HNSW, hard filters, weighted RRF, and Cohere Rerank."
    ),
    instructions=(
        "Use search_products to create a source-attributed candidate set. "
        "Use get_product_evidence only with returned product IDs, and use "
        "inspect_retrieval_run with the returned run ID to explain ranking."
    ),
    version="0.2.0",
)


@mcp.tool(
    title="Search catalog products",
    description=(
        "Run the canonical filtered hybrid retrieval pipeline and return "
        "source-attributed products with candidate-level rank signals."
    ),
    annotations=READ_ONLY_QUERY,
    structured_output=True,
)
def search_products(
    query: str,
    domain: Domain | None = None,
    category_key: str | None = None,
    brand: str | None = None,
    availability: Availability | None = None,
    in_stock_only: bool = False,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    min_rating: float | None = None,
    attributes: dict[str, Any] | None = None,
    limit: int = 12,
    include_diagnostics: bool = True,
    rerank: bool = True,
) -> SearchResponse:
    """Search products with Aurora PostgreSQL hybrid retrieval."""
    filters = SearchFilters(
        domain=domain,
        category_key=category_key,
        brand=brand,
        availability=availability,
        in_stock_only=in_stock_only,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        min_rating=min_rating,
        attributes=attributes or {},
    )
    request = SearchRequest(
        query=query,
        filters=filters,
        limit=limit,
        include_diagnostics=include_diagnostics,
        rerank=rerank,
    )
    request_payload = request.model_dump(mode="json", exclude_none=True)
    request_payload["filters"] = filters.as_sql_json()
    payload = get_api_client().post(
        "/search",
        request_payload,
    )
    return SearchResponse.model_validate(payload)


@mcp.tool(
    title="Get product evidence",
    description=(
        "Read one product revision with specifications, approved media, "
        "source attribution, and review evidence."
    ),
    annotations=READ_ONLY_LOOKUP,
    structured_output=True,
)
def get_product_evidence(product_id: int) -> ProductDetail:
    """Read one product and its inspectable evidence."""
    payload = get_api_client().get(f"/products/{product_id}")
    return ProductDetail.model_validate(payload)


@mcp.tool(
    title="Inspect a retrieval run",
    description=(
        "Replay persisted lexical, trigram, semantic, RRF, rerank, business, "
        "filter, timing, and final-order signals for one search run."
    ),
    annotations=READ_ONLY_LOOKUP,
    structured_output=True,
)
def inspect_retrieval_run(run_id: str) -> RetrievalRunResponse:
    """Read the ranking provenance persisted for a retrieval run."""
    parsed_run_id = UUID(run_id)
    # The API serves this as `/api/retrieval/events/{search_event_id}`; the
    # client's base URL already carries `/api`. Requesting `/retrieval/runs/`
    # returned HTTP 404 for every call.
    payload = get_api_client().get(f"/retrieval/events/{parsed_run_id}")
    return RetrievalRunResponse.model_validate(payload)


def create_http_app(*, host: str | None = None) -> Any:
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=host or os.getenv("MCP_HOST", "127.0.0.1"),
    )


app = create_http_app()


def main() -> None:
    mcp.run(
        "streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8001")),
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
