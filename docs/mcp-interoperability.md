# Mosaic MCP portable tool contract

## Workshop boundary

MCP is an instructor-led interoperability checkpoint inside Lab 3, not a
separate protocol lab. It makes the inspected hybrid retrieval system portable
to another compatible agent host through standard product-discovery tools.

The checkpoint proves one architectural point:

```text
Strands product agent -+
React workshop UI -----+-> typed FastAPI -> canonical Aurora retrieval SQL
MCP-compatible host ---+
```

The adapters do not reimplement filters, retrieval arms, RRF, reranking, or
ranking diagnostics.

## Protocol and dependency boundary

The MCP service implements specification revision `2026-07-28` with the MCP
Python SDK `2.0.0`. Its Streamable HTTP endpoint is stateless and supports
`server/discover`, the per-request protocol envelope, and the `Mcp-Method` and
`Mcp-Name` routing headers. This is the portable contract; it does not create
another retrieval pipeline or agent harness.

Strands Agents `1.48.0` requires MCP `<2`. The FastAPI/Strands environment and
the MCP server therefore use separate Python environments:

```text
.venv/                 FastAPI, Strands, PostgreSQL, and model clients
mcp-server/.venv/      Mosaic MCP 2.0 adapter and HTTP client
```

This is intentional. Both processes consume the same API and Pydantic response
contracts while preserving their compatible dependency sets.

## Read-only tools

| Tool | API route | Purpose |
|---|---|---|
| `search_products` | `POST /api/search` | Run filtered hybrid retrieval and return source-attributed products |
| `get_product_evidence` | `POST /api/products/{product_id}/evidence` | Rank source-addressable specifications and reviews for the supplied evidence question |
| `inspect_retrieval_run` | `GET /api/retrieval/events/{search_event_id}` | Replay arm ranks, raw scores, RRF, rerank, filter, and timing signals |

All three tools advertise `readOnlyHint=true` and
`destructiveHint=false`. Search is not marked idempotent because every search
persists a new retrieval run for diagnostics and replay.

## Run the adapter

Start the canonical API:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@YOUR-CLUSTER.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/mosaic_catalog?sslmode=require'
uvicorn service.main:app --host 127.0.0.1 --port 8000
```

Install and start the isolated MCP service:

```bash
make mcp-install
make mcp-serve
```

The endpoint is `http://127.0.0.1:8001/mcp`. Override the upstream API with
`CATALOG_API_URL` and the listener with `MCP_HOST` or `MCP_PORT`.

Run its protocol and adapter tests with:

```bash
make mcp-test
```

## Participant checkpoint

1. Connect an MCP-compatible inspector or host to `/mcp`.
2. Confirm discovery negotiates `2026-07-28`.
3. List the three typed, read-only tools.
4. Call `search_products` with the Lab 3 query and a hard price or availability
   filter.
5. Pass the returned run ID to `inspect_retrieval_run`.
6. Compare the MCP result with the Retrieval Lab UI and confirm both show the
   same persisted PostgreSQL ranking signals.

Authentication, tenant scope, AgentCore hosting, MCP Apps, Tasks, and
production authorization policy remain take-home extensions.
