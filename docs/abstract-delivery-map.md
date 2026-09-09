# Delivering the abstract

The [submitted abstract](session-abstract.md) describes the complete application. The three required labs repair and prove one part of it each; the flex exercise adds a tool. The mission file owns their questions, filters, targets, timings and assertions.

| Promise | Where participants encounter it | What they do |
|---|---|---|
| Aurora as search and context engine | All three labs | Inspect saved searches, agent activity and evidence in Aurora |
| Full-text search | Retrieve | Read the stemming comparison; inspect the GIN index in Go deeper |
| pgvector semantic similarity | Retrieve; Scale & HNSW | Inspect meaning matches; optionally read the existing index plan |
| SQL and metadata filters | Retrieve, G-012 | Run the request and prove the refurbished sibling never became a candidate |
| Fuzzy matching | Retrieve | Reconnect the close-spelling candidate channel |
| Reciprocal rank fusion | Rank | Implement `1 / (k + source_rank)` and verify its contributions |
| Model-based reranking | Rank | Compare earlier and final positions; explain why reranking hid the defect |
| Source attribution | Reason | Register evidence IDs by record and product; resolve every citation |
| Retrieval diagnostics | All three labs | Read filters, candidates, fused rank, rerank, evidence IDs and latency |
| Wire retrieval into agent tools | Reason; build-a-tool flex | Repair an evidence tool; in flex implement filters and register a typed Strands tool |
| Decompose questions | Reason; Plan my workspace | Identify the independent keyboard and chair searches and their filters |
| Gather targeted evidence | Reason | Trace the evidence tool and the records it returns |
| Compare sources | Check the sources | Compare specification and sample review, including missing support |
| Explain ranking signals | Rank; agent activity | Inspect source positions, fusion contributions and the explanation tool |
| Synthesize cited answers | Reason | See the repaired answer and inspect a rejected claim example in Go deeper |
| Working code, schema patterns, ranking templates | Conclusion; hybrid retrieval skill | Download the skill with its API mapping and adaptation references; use the implementation map for schema and ranking templates |

The completion gate remains inside Lab 3. Its saved-run option repeats the checks against current Aurora records without issuing two additional model calls. It rejects changed code or settings, missing runs, a rebroken seam and changed citation records.

The build-a-tool guide is the default flex beat. Scale & HNSW is the fallback. AgentCore belongs in the closing architecture slide: preferences may shape retrieval, while product claims still require catalog evidence. Runtime demonstrations require a rehearsed endpoint.

The main takeaway is `skills/mosaic-hybrid-retrieval/`, downloadable from `/api/skill-package`. The builder kit supports the optional exercise; it does not replace the skill. Participant instructions live in the sibling Workshop Studio repository, not in Mosaic’s main Playground.
