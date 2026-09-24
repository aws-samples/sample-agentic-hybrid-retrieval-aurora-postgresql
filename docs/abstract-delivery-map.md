# Delivering the abstract

The [submitted abstract](session-abstract.md) describes the complete application. The three required labs repair and prove one part of it each; the flex exercise adds a tool. The mission file owns their questions, filters, targets, timings and assertions.

The opening makes the scaffolding explicit: the catalog, embeddings and
application are supplied; participants implement and prove three critical
connections. The guide's page shape, graded work and pacing are recorded in the
[L400 lab design](l400-lab-design.md).

## The three labs

Behind Alex's shopping goals, participants complete three technical labs. Each
asks more than the last (explain a mechanism, write an algorithm, specify a
contract), and each is graded against an answer the grader computes itself.

- **Lab 1 — Build hybrid retrieval · 10 min.** A transposed product ID makes
  Alex's saved headphones vanish. Participants use PostgreSQL's own functions
  (`tsvector` lexemes, `pg_trgm` word similarity, pgvector distance) to show why
  only one search method can recover it, then reconnect that method. They then
  write a recall query for the vector search they didn't touch. The grader runs
  it under the planner's plan and with HNSW forced: in recorded runs the forced plan was roughly 6–7×
  faster yet missed half or more of the true nearest neighbours. **Lesson: a full
  result list is not evidence of good recall; only a comparison with exact
  results measures it.**
- **Lab 2 — Fuse, rerank, and inspect · 10 min.** The monitor that documents 90W
  USB-C charging never reaches the reranker. Participants write reciprocal rank
  fusion in SQL, graded at five values of `k`. Their version shows the saved run
  had only two distinct scores, so the product-ID tie-breaker, not relevance,
  picked the 50 products sent to Cohere Rerank. After repairing production, they
  propose one retrieval change under a rule they set in advance. The grader
  replays it over 141 judged shopper queries, and adopting and rejecting both
  pass if the decision follows the rule. **Lesson: fusion only works if positions
  count, and a tuning decision needs a judged set and a rule chosen before seeing
  results.**
- **Lab 3 — Build the retrieval agent · 20 min.** A Strands agent finds the right
  monitor and chair and retrieves their evidence, then refuses to answer (HTTP
  503): the records were never registered as citable. Participants write that
  contract as pytest tests, which must reject four faulty implementations, then
  repair the handoff. They check that every citation matches its product,
  revision and quote, and separate what cited records support from reviews that
  were merely available. The finale proves from the agent's own saved searches
  that their Lab 1 and Lab 2 repairs shaped the answer. **Lesson: finding a
  source, being allowed to cite it, and what it actually supports are three
  separate checks; the agent chooses the steps, but tests and application code
  decide what it may cite.**

The forced-HNSW figures come from four recorded runs of the Lab 1 grader on the workshop
catalog (forced recall 0.287 on 2026-09-23, then 0.440, 0.467 and 0.467 on 2026-09-24;
about 286 ms for the planner's exact plan against 39–47 ms forced). The query vector is
re-embedded on each run, so the guides print no fixed number.

## Where each promise is delivered

| Promise | Where participants encounter it | What they do |
|---|---|---|
| Aurora as search and context engine | All three labs | Inspect saved searches, agent activity and evidence in Aurora |
| Full-text search | Retrieve | Compare the query's and the listing's lexemes to show why word search cannot match a transposed ID |
| pgvector semantic similarity | Retrieve; Scale & HNSW | Write an index-proof recall query graded under the planner's plan and forced HNSW; optionally build and shrink a partial HNSW index |
| SQL and metadata filters | Retrieve; Rank | The validator proves every saved candidate respects the Bose/headphones and Dell/monitor filters before reranking |
| Fuzzy matching | Retrieve | Read `word_similarity` against whole-string similarity, then reconnect the close-spelling channel from its contract |
| Reciprocal rank fusion | Rank | Write RRF in SQL (graded at five `k` values) and make production's `1 / (k + source_rank)` agree with it |
| Model-based reranking | Rank | Compare combined and final positions; decide one retrieval setting on 141 judged queries within one billed rerank unit |
| Source attribution | Reason | Specify evidence registration as tests, repair it, and resolve every citation to its product, revision and quote |
| Retrieval diagnostics | All three labs | Read filters, candidate positions, fused rank, reranked rank, evidence IDs and the agent's ordered tool sequence |
| Wire retrieval into agent tools | Reason; build-a-tool flex | Repair the evidence handoff the tools rely on; in flex, implement filters and register a typed Strands tool |
| Decompose questions | Reason; Plan my workspace | Read the agent's separate monitor and chair searches and their filters |
| Gather targeted evidence | Reason | Trace the evidence tool and the records it returned before synthesis failed |
| Compare sources | Reason; Check the sources | Count cited specifications and reviews against imported reviews and source rating counts |
| Explain ranking signals | Rank; agent activity | Inspect source positions, fusion contributions and the explanation tool |
| Synthesize cited answers | Reason | Run the repaired answer, challenge altered citations, and close Alex's brief from the saved records |
| Working code, schema patterns, ranking templates | Conclusion: Take hybrid agentic search into your own agent | Download the skill and the implementation package; the full checkout supplies SQL, evaluations and citation checks |

The completion gate remains inside Lab 3. Its saved-run option repeats the checks against current Aurora records without issuing two additional model calls. It rejects changed code or settings, missing runs, a rebroken seam and changed citation records.

The customer story is **find options → establish their order → support a
decision**. Keep the stage names Retrieve, Rank and Reason. Lab 1 recovers the
Bose QuietComfort 35 II Alex saved; Lab 2 keeps the Dell U2720Q, a 27-inch 4K
monitor documenting USB-C charging up to 90W, in reach of the reranker; Lab 3
asks the agent to check that monitor and the Steelcase Gesture chair against
their sources. The finale, **Bring Alex's office home**, reads the participant's three
repairs, decisions and citations back from Aurora without
another model call. The [presenter brief](../workshop.md) owns the spoken
narrative and transitions.

The build-a-tool guide is the default flex beat. Scale & HNSW is the fallback. AgentCore belongs in the closing architecture slide: preferences may shape retrieval, while product claims still require catalog evidence. Runtime demonstrations require a rehearsed endpoint.

The closing message is **Take hybrid agentic search into your own agent**.
Introduce reuse in the opening and connect each lab's repair to the behavior an
agent relies on. Close on an existing checked answer, then show **Download the
skill** (`/api/skill-package`) and **Adapt the implementation**
(`/api/builder-package`). The first provides calling instructions and API
mappings for the running service; the second provides reference SQL and the
implementation map. The full checkout supplies runnable code, evaluations and
citation checks. Participant instructions live in the sibling Workshop Studio
repository.
