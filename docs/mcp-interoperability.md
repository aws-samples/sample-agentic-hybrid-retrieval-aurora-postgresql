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
7. Compare the MCP result with the Playground UI and confirm both show the
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

## The gate is not the guard

Optional, and outside the session path. Nothing here is deployed by the
workshop and there are no setup steps to run at a table. It exists because the
question always comes: could a managed gateway handle authorization for us.

Amazon Bedrock AgentCore Gateway can sit in front of the three tools above and
take the concerns this adapter deliberately does not hold:

- **Authentication at the edge.** Callers present IAM or OAuth credentials to
  the Gateway. The workshop's local endpoint has no caller identity at all; it
  assumes one attendee on a disposable instance, which is why
  `inspect_retrieval_run` is documented above as unscoped.
- **Discovery.** A host that has never seen Mosaic can list the tools and their
  typed schemas from one managed endpoint.
- **Transport and hosting.** The connection terminates at the Gateway, so the
  adapter keeps its single job of forwarding typed calls to the API.

What a Gateway does not do is authorize evidence. Put one in front of
`search_products` and the tool still returns product IDs, exactly as it does
now, and the application still decides which of them a later call may act on.
`get_product_evidence` still requires the `retrieval_scope_id` that search
returned, and `service/retrieval_scope.py` still decides whether the requested
product sat inside the authorized window; a product from the fused pool that
the search did not return still fails with HTTP 404. Lab 3's evidence
registration still decides, separately and per turn, what synthesis may cite.

Keep the two questions in different places, because they are different
questions. Authentication answers who is calling. The guard answers what an
answer is allowed to stand on, and that answer lives in application state
backed by Aurora, not in an edge policy. A Gateway that has authenticated a
caller has authorized nothing about evidence, and a workshop that let the two
collapse would be teaching the wrong lesson.
