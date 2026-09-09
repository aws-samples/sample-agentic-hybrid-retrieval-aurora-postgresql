# Mosaic parking lot

Reviewed 9 September 2026. These are optional product and integration extensions,
not extra required workshop labs. The primary takeaway remains the Mosaic Hybrid
Retrieval Skill.

| Idea | Current state | Next useful increment |
|---|---|---|
| Session & Memory | AgentCore events, all four built-in strategies, live record inspection, relevant recall, and Aurora session history | Rehearse a completed episodic interaction and inspect its reflection when available |
| Memory customization | Built-in behavior is live; overrides and self-managed strategies are explained | One scoped override, showing the changed instructions and resulting records |
| AgentCore Runtime | Adapter, container definition and tests exist | Build the image and verify a deployed invocation against the same Aurora turn records |
| AgentCore Gateway | Standalone MCP server exists; no Gateway connection | Connect the existing tool boundary after Runtime is verified |
| Memory deletion | Actor-scoped reads and event retention exist | Account-level record and event deletion, with clear retention behavior |
| Product cards in answers | Shared cards appear inline with answer text, with photography, price, rating and availability; Retrieve and Rank use the same component | Review the conference laptop and projector presentation |
| Why didn't this match? | Match explanations and applied filters exist | Return a specific product's stock, required-attribute or price exclusions from the backend |
| Download this run | Lab proof and benchmark downloads exist | One export containing filters, candidates, ranks, model IDs, timings, searches and evidence references |
| How this product is indexed | Searchable data and embedding metadata exist in the backend | Product inspector with weighted text, searchable attributes and embedding identity |
| Blind judging | Not implemented | Anonymous result lists, a choice, then method and reranking reveal |
| Budget comparison | Separate runs persist | Optional shopping comparison; outside the Session & Memory teaching flow |

Suggested next AgentCore work: verify Runtime end to end, then choose one strategy
override or Gateway integration. Episodic extraction and reflection need a live
rehearsal before being presented as a completed demonstration. A configured
strategy alone does not prove that an episode was extracted.

Already delivered: the three-column pipeline, staged progress, stable search
selection, answer/product ordering, source comparison, multi-part requests,
3D HNSW, and refreshed scale measurements. The optional build-a-tool exercise
lives in Workshop Studio and take-home documentation.
