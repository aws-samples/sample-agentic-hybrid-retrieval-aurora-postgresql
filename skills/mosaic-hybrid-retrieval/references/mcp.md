# Connect the retrieval tools through MCP

Use this mapping with the separate Mosaic portable MCP adapter. Lab 3's
managed Gateway connection has its own IAM authentication and execution hooks;
follow `docs/agentcore-runtime.md` in the full checkout for that path.

## Connect

From a full Mosaic checkout with its API already running and the authorized
settings loaded, run `make mcp-install`, then `make mcp-serve`. The default
Streamable HTTP endpoint is `http://127.0.0.1:8001/mcp`. Configure a compatible
host on that same machine with this URL. The adapter uses protocol `2026-07-28`;
check the host's compatibility and list tools before sending a request.

The adapter connects to `CATALOG_API_URL` (default `http://127.0.0.1:8000/api`)
and uses the configured origin credential when required. Keep credentials in
host configuration, never in the skill or a prompt. Do not expose the loopback
adapter remotely without adding authenticated access and owner authorization.
The Workshop Studio service expires with the event; deploy a compatible service
for continued use. This skill ZIP does not install that service or MCP adapter.

## Map the workflow

| Workflow operation | MCP tool | Inputs to carry forward |
|---|---|---|
| Search | `search_products` | `query` and supported structured filters; save `search_event_id` |
| Read sources | `get_product_evidence` | `retrieval_scope_id` = saved search ID, a returned `product_id`, and `evidence_query` |
| Compare | `compare_products` | `retrieval_scope_id` = saved search ID and two to five distinct returned `product_ids` |
| Explain ranking | `inspect_retrieval_run` | `run_id` = saved search ID |

Comparison and evidence are restricted to products granted by that search.
Keep separate scopes for separate searches. The portable adapter's inspection
is not bound to a user identity; a shared deployment must add owner checks.

The tools do not expose arbitrary SQL or product writes. Search appends audit
records. Read-only annotations describe intended behavior; the service and
database privileges enforce the actual boundary. No answer-synthesis tool is
exposed here: use your host's trusted citation validator, or use Mosaic's
complete answer endpoint instead of running a second orchestration loop.

See [HTTP mapping](http-api.md), [composition](composition.md), and
[quality checks](quality-checks.md) for the corresponding contracts.
