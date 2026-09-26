"""The canonical SQL API exposed as an MCP target for AgentCore Gateway."""

from uuid import UUID

from mcp.server.fastmcp import FastMCP

from service.lab_validation_receipt import source_digest
from service.main import get_question_ranked_product_evidence, retrieval_event, search
from service.models import ProductEvidenceRequest, SearchRequest

mcp = FastMCP(
    "Mosaic SQL tools",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
)


def _result(value) -> dict:
    return {"source_sha256": source_digest(), "data": value.model_dump(mode="json")}


@mcp.tool()
def search_products(request: SearchRequest) -> dict:
    """Search Aurora with shared filters, full-text search, pg_trgm, pgvector and reranking."""
    return _result(search(request))


@mcp.tool()
def get_product_evidence(product_id: int, request: ProductEvidenceRequest) -> dict:
    """Retrieve evidence only for a product granted by the supplied search event."""
    return _result(get_question_ranked_product_evidence(product_id, request))


@mcp.tool()
def inspect_retrieval_run(run_id: UUID) -> dict:
    """Read the candidate ranks and saved results for a retrieval event."""
    return _result(retrieval_event(run_id))
