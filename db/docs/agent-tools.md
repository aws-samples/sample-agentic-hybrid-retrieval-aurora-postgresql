# Agent tool contracts

The runnable contracts are in `db/config/agent_tool_contracts.json`. The agent implements and registers them in `service/agent_tools.py` and `service/agent.py`.

| Agent tool | Input | Result |
|---|---|---|
| `search_products` | Query and structured filters | Ranked products, a saved search ID and diagnostics |
| `get_product_evidence` | Authorized product ID and a focused evidence question | Question-ranked source records with IDs and revisions |
| `compare_products` | Authorized product IDs | Catalog attributes, constraints, source revisions and ranking signals |
| `explain_retrieval` | Authorized saved search ID | Recorded per-method ranks, fusion contributions, reranker scores and timings |
| `synthesize_cited_answer` | Question and selected product IDs | Answer checked against the allowed evidence records |

All five read catalog data. The application records their activity in `mosaic.agent_tool_event`. Comparison of catalog fields is distinct from weighing source claims: the agent reads specification and review evidence, then synthesis checks its citations and supported claims.

For a small typed tool you can build and run, see [Build a retrieval tool](../../docs/build-retrieval-tool.md). For the schema, SQL and application adaptation points, see [Use this in your app](../../docs/use-in-your-app.md).
