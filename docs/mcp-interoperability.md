# Mosaic MCP portable tool contract

## Workshop boundary

MCP appears only in the productionization reveal after Lab 3. It is not a
participant build, protocol lesson, or fourth lab. It shows why keeping
retrieval behind typed contracts makes the inspected system portable to another
compatible agent host.

The checkpoint proves one architectural point:

```text
Strands product agent -+
React workshop UI -----+-> typed FastAPI -> canonical Aurora retrieval SQL
MCP-compatible host ---+
```

The adapters do not reimplement filters, retrieval arms, RRF, reranking, or
ranking diagnostics.

`scripts/tool_contracts.py --check` proves the portable boundary that exists in
this repository: the two shared agent/MCP tools retain their version, output
schema, and read-only policy, while each transport keeps its own input shape and
trace. It does not claim a deployed Amazon Bedrock AgentCore Gateway or
runtime-result parity that was not measured.

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
| `get_product_evidence` | `POST /api/products/{product_id}/evidence` | Rank specifications and reviews for one product the supplied `retrieval_scope_id` granted |
| `inspect_retrieval_run` | `GET /api/retrieval/events/{search_event_id}` | Replay arm ranks, raw scores, RRF, rerank, filter, and timing signals. Unscoped by design: any valid ID resolves, on the single-attendee disposable-instance assumption. |

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

## Optional operator check

1. Connect an MCP-compatible inspector or host to `/mcp`.
2. Confirm discovery negotiates `2026-07-28`.
3. List the three typed, catalog-read-only tools.
4. Call `search_products` with the Lab 3 query and a hard price or availability
   filter, and keep the `search_event_id` it returns.
5. Call `get_product_evidence` with that ID as `retrieval_scope_id` and one
   returned product. Then call it again with a product ID it did not return and
   confirm HTTP 404.
6. Pass the returned run ID to `inspect_retrieval_run`.
7. Compare the MCP result with the Retrieval Lab UI and confirm both show the
   same persisted PostgreSQL ranking signals.

This optional check proves candidate, eligibility, RRF, and evidence payload
preservation through the local MCP adapter, and it now also proves the grant
boundary: pass a `product_id` from the pool that the retrieval did not return
within its `authorized_limit` and `get_product_evidence` fails with HTTP 404.
The adapter forwards the scope and holds no policy of its own; the authority is
`service/retrieval_scope.py`. Citation authorization remains separate and
turn-local: retrieving scoped evidence does not authorize it for synthesis.

[Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
can host custom agent code, and
[AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
can expose APIs, Lambda functions, or MCP servers as tools. Authentication,
tenant scope, managed hosting, and production authorization policy remain
take-home extensions.
