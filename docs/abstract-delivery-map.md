# Delivering the abstract

The [submitted abstract](session-abstract.md) describes the complete application. The three required labs repair and prove one part of it each; the flex exercise adds a tool. The mission file owns their questions, filters, targets, timings and assertions.

The opening makes the scaffolding explicit: the catalog, embeddings and
application are supplied; participants implement and prove three critical
connections. The guide's page shape and task structure are recorded in the
[lab exercise design](superpowers/specs/2026-09-19-lab-exercise-design.md).

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
| Decompose questions | Reason; Plan my workspace | Identify the independent monitor and chair searches and their filters |
| Gather targeted evidence | Reason | Trace the evidence tool and the records it returns |
| Compare sources | Check the sources | Compare specification and sample review, including missing support |
| Explain ranking signals | Rank; agent activity | Inspect source positions, fusion contributions and the explanation tool |
| Synthesize cited answers | Reason | See the repaired answer and inspect a rejected claim example in Go deeper |
| Working code, schema patterns, ranking templates | Conclusion: Use what you built in your own agent | Follow the implementation map for SQL, evaluations and citation checks; use the skill's calling instructions to connect another agent to the running service |

The completion gate remains inside Lab 3. Its saved-run option repeats the checks against current Aurora records without issuing two additional model calls. It rejects changed code or settings, missing runs, a rebroken seam and changed citation records.

The customer story is **find options → establish their order → support a
decision**. Keep the stage names Retrieve, Rank and Reason. Lab 2 establishes a
chair shortlist; Lab 3 adds a 32-inch 4K monitor with USB-C video and 90W charging and refines the chair
requirement to 12-hour use and dynamic lumbar support, each item under $800.
Fresh searches can therefore support a different chair. This is not a saved
selection or Memory handoff. The finale traces an existing answer claim to its
source, product, search and ranking without another model call. The
[presenter brief](../workshop.md) owns the spoken narrative and transitions.

The build-a-tool guide is the default flex beat. Scale & HNSW is the fallback. AgentCore belongs in the closing architecture slide: preferences may shape retrieval, while product claims still require catalog evidence. Runtime demonstrations require a rehearsed endpoint.

The closing message is **Use what you built in your own agent**. Introduce reuse
in the opening and connect each lab's repair to the behavior an agent relies
on. Close on an existing checked answer, then show **Adapt the implementation**
(`/api/builder-package`) and **Download the skill** (`/api/skill-package`). The
first provides reference SQL and the implementation map; the second provides
calling instructions and API mappings for the running service. The full
checkout supplies runnable code, evaluations and citation checks. Participant
instructions live in the sibling Workshop Studio repository.
