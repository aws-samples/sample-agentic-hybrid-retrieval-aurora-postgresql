# Mosaic MCP portable tool contract

## Workshop boundary

Lab 3 already uses MCP through AgentCore Gateway to call the managed SQL tools.
The take-home adapter described here connects another compatible host to the
same retrieval API. It adds no required lab and is not automatically exposed
as a public MCP endpoint by the workshop.

The checkpoint proves one architectural point:

```text
Strands product agent -+
React workshop UI -----+-> typed FastAPI -> canonical Aurora retrieval SQL
MCP-compatible host ---+
```

The adapters do not reimplement filters, retrieval arms, RRF, reranking, or
ranking diagnostics.

`scripts/checks/tool_contracts.py --check` proves the portable boundary that exists in
this repository: the shared agent/MCP capabilities retain their version, output
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
mcp-server/.venv/      Mosaic MCP adapter and HTTP client
```

This is intentional. Both processes consume the same API and Pydantic response
contracts while preserving their compatible dependency sets.

## Catalog-read-only tools

| Tool | API route | Purpose |
|---|---|---|
| `search_products` | `POST /api/search` | Run filtered hybrid retrieval and return source-attributed products |
| `get_product_evidence` | `POST /api/products/{product_id}/evidence` | Rank specifications and reviews for one product the supplied `retrieval_scope_id` granted |
| `compare_products` | `POST /api/retrieval/events/{search_event_id}/compare` | Compare two to five distinct products granted by the supplied `retrieval_scope_id` |
| `inspect_retrieval_run` | `GET /api/retrieval/events/{search_event_id}` | Replay arm ranks, raw scores, RRF, rerank, filter, and timing signals. Unscoped by design: any valid ID resolves, on the single-attendee disposable-instance assumption. |

All four tools advertise `readOnlyHint=true` and
`destructiveHint=false`. Search is not marked idempotent because every search
persists a new retrieval run for diagnostics and replay.

## Run the adapter

Follow [development setup](development.md#set-up-the-application) to configure
the Aurora-backed API, then start it from that configured environment:

```bash
make api-serve
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
3. List the four typed, catalog-read-only tools.
4. Call `search_products` with the Lab 3 query and a hard price or availability
   filter, and keep the `search_event_id` it returns.
5. Call `get_product_evidence` with that ID as `retrieval_scope_id` and one
   returned product. Then call it again with a product ID it did not return and
   confirm HTTP 404.
6. Call `compare_products` with that scope and two returned IDs. Confirm a product outside the granted window is refused, then pass the returned run ID to `inspect_retrieval_run`.
7. Compare the MCP result with the Playground UI and confirm both show the
   same persisted PostgreSQL ranking signals.

This optional check proves candidate, eligibility, RRF, and evidence payload
preservation through the local MCP adapter, and it now also proves the grant
boundary: pass a `product_id` from the pool that the retrieval did not return
within its `authorized_limit` and `get_product_evidence` fails with HTTP 404.
The adapter forwards the scope and holds no policy of its own; the authority is
`service/retrieval_scope.py`. Citation authorization remains separate and
turn-local: retrieving scoped evidence does not authorize it for synthesis.

## Managed Gateway and the portable adapter

The workshop provisions [AgentCore Runtime](agentcore-runtime.md) and Gateway
for Lab 3. Its agent uses the signed Gateway MCP endpoint and the supplied
execution hooks; those tools preserve per-turn evidence authorization. A generic
client needs support for that endpoint's IAM authentication. Do not replace the
managed agent's execution hooks with a bare MCP client.

The separate `mcp-server` package above exposes search, evidence, comparison and
inspection through the existing HTTP API. Keep its default loopback listener
for a host on the same machine. This adapter has no caller-authentication layer:
a remote or shared deployment must add authenticated access and owner-scoped
replay before exposing it. The downstream origin header authenticates the
adapter to the API; it is not an identity for each MCP caller. Read
[security boundaries](security-boundaries.md) before adapting it.

## Permissions and workflow guidance

Connect retrieval tools, then add the skill to guide their use. The downloadable
[skill](../skills/mosaic-hybrid-retrieval/SKILL.md) contains instructions and
references, including the exact [MCP mapping](../skills/mosaic-hybrid-retrieval/references/mcp.md).
It can accompany an MCP connection or the HTTP API. Neither installing a skill
nor declaring `readOnlyHint=true` grants or restricts database privileges.

Mosaic's retrieval operations do not mutate catalog records. Search still writes
audit records, so it is not an idempotent, zero-write database transaction.
Service code validates inputs and retrieval grants, and the runtime database
role limits catalog and diagnostic access. Do not give an agent administrator
credentials merely to use a retrieval tool. The host's other tools and
credentials remain part of its access boundary.

### The gate is not the guard

Gateway authenticates the managed caller and exposes authorized tools. Mosaic
still checks which products a retrieval granted and which evidence an answer
may cite. For this adapter, `get_product_evidence` and `compare_products` forward
the saved scope; `service/retrieval_scope.py` refuses ungranted products. A saved
scope is not a user identity, and a valid citation ID alone is not proof that a
claim is supported.

### Official references

- [MCP: Tool Annotations as Risk Vocabulary](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) explains why read-only hints are not enforcement.
- [MCP: Server Instructions](https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/) explains workflow guidance and its limits.
- [Agent Skills overview](https://agentskills.io/home) and [format specification](https://agentskills.io/specification) describe the portable instruction package.
