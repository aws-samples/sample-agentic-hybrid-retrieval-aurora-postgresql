# Delivering the abstract

The [submitted abstract](session-abstract.md) describes the complete application. The three required labs repair and prove one part of it each; the optional exercises add a tool. The mission file owns their questions, filters, targets, timings and assertions.

The opening makes the scaffolding explicit: the catalog, embeddings and
application are supplied; participants implement and prove three critical
connections. The guide's page shape, graded work and pacing are recorded in the
[L400 lab design](l400-lab-design.md).

## The three labs

Behind Alex's shopping goals, participants complete three technical labs. Each
asks more than the last (find a lost candidate, fix a formula and judge a change,
build and deploy an agent), and each is graded against an answer the grader computes itself.

- **Lab 1 — Debug hybrid search · 10 min.** A transposed product ID makes
  Alex's saved headphones vanish. Participants use PostgreSQL's own functions
  (`tsvector` lexemes, `pg_trgm` word similarity, pgvector distance) to show why
  only one search method recovers it, then find why its candidates never reach
  fusion and add the missing branch. An optional
  Go deeper step has them write a recall query for the vector search they didn't
  touch. The grader runs
  it under the planner's plan and with HNSW forced: in recorded runs the forced plan was roughly 6–7×
  faster yet missed half or more of the true nearest neighbours. **Lesson: a full
  result list is not evidence of good recall; only a comparison with exact
  results measures it.**
- **Lab 2 — Tune rank fusion and reranking · 10 min.** The monitor that documents
  USB-C charging up to 90W over one cable never reaches the reranker. A provided
  query shows the collapsed contributions tie every single-search candidate, so the
  product-ID tie-breaker, not relevance, decides the 50 products sent to Cohere
  Rerank and keeps the oldest listings in the pool. Participants fix one line, graded
  at five values of `k`, then read the measured effect of three settings derived from
  the served profile over 141 judged shopper queries and write what they would ship.
  **Lesson: fusion only works if positions count, and a tuning claim needs a judged
  set.**
- **Lab 3 — Build and deploy the agent · 20 min.** Participants connect the
  Gateway SQL tools, complete the Strands agent constructor, add an instruction
  and deploy it to AgentCore Runtime. They ask Alex's three-product room question,
  open a citation and change a requirement in a follow-up. The actual managed
  run is checked at completion without another model call. **Lesson: the SQL
  from Labs 1 and 2 becomes a managed agent capability, with product claims
  supported by retrieved sources.**

The forced-HNSW figures are a historical record. They come from four runs of the Lab 1
grader on 2026-09-23 and 2026-09-24, before the cutover to `reviews-2023-v2`, so they
describe the retired `reviews-2023-500k-v1` catalog: forced recall 0.287 on 2026-09-23,
then 0.440, 0.467 and 0.467 on 2026-09-24, and about 286 ms for the planner's exact plan
against 39–47 ms forced. The query vector is re-embedded on each run, so the guides print
no fixed number. Current measurements on `reviews-2023-v2` are in
`data/benchmarks/hnsw_measured.json`; they use a different query sample and method, so
they are not a like-for-like replacement for these figures.

## Where each promise is delivered

| Promise | Where participants encounter it | What they do |
|---|---|---|
| Aurora as search and context engine | All three labs | Inspect saved searches, agent activity and evidence in Aurora |
| Full-text search | Retrieve | Compare the query's and the listing's lexemes to show why word search cannot match a transposed ID |
| pgvector semantic similarity | Retrieve (optional); Scale & HNSW | Optionally write an index-proof recall query graded under the planner's plan and forced HNSW; optionally build and shrink a partial HNSW index |
| SQL and metadata filters | Retrieve; Rank | The validator proves every saved candidate respects the Logitech/headphones and Dell/monitor filters before reranking |
| Fuzzy matching | Retrieve | Read `word_similarity` against whole-string similarity, then add the close-spelling branch that fusion never reads |
| Reciprocal rank fusion | Rank | Fix production's `1 / (k + source_rank)`, graded at five `k` values |
| Model-based reranking | Rank | Compare combined and final positions; judge three measured settings on 141 judged queries within one billed rerank unit |
| Source attribution | Reason | Build the agent, ask a product question and open its citations |
| Retrieval diagnostics | All three labs | Read filters, candidate positions, fused rank, reranked rank, evidence IDs and the agent's ordered tool sequence |
| Wire retrieval into agent tools | Reason; build-a-tool exercise | Connect the SQL tools through Gateway and deploy the Strands agent to Runtime |
| Decompose questions | Reason; Complete my room | Read the agent's separate headphone, monitor and chair searches and their filters |
| Gather targeted evidence | Reason | Inspect the evidence tool and the product records it returned |
| Compare sources | Reason; Check the sources | Count cited specifications and reviews against imported reviews and source rating counts |
| Explain ranking signals | Rank; agent activity | Inspect source positions, fusion contributions and the explanation tool |
| Synthesize cited answers | Reason | Ask Alex's question, open a citation and change a requirement in a follow-up |
| Working code, schema patterns, ranking templates | Conclusion: Take this retrieval into your own agent | Download the skill and the implementation package; the full checkout supplies SQL, evaluations and citation checks |

The completion gate remains inside Lab 3. Its saved-run option repeats the checks against current Aurora records without issuing two additional model calls. It rejects changed code or settings, missing runs, a rebroken seam and changed citation records.

The customer story is **find options → establish their order → support a
decision**. Keep the stage names Retrieve, Rank and Reason. Lab 1 recovers the
Logitech Zone 900 Alex saved; Lab 2 keeps the ViewSonic VG2756-4K, a
27-inch 4K monitor documenting USB-C charging up to 90W over one cable, in
reach of the reranker; Lab 3 asks the agent to check those headphones, that monitor and the
Steelcase Gesture chair against their sources. The finale, **Bring Alex's office home**, reads the participant's three
repairs, decisions and citations back from Aurora without
another model call. The [presenter brief](../workshop.md) owns the spoken
narrative and transitions.

Session & Memory leads the untimed optional exercises; the build-a-tool guide and Scale & HNSW are the alternatives. AgentCore Runtime and Gateway are the deployed Lab 3 path. Memory can carry preferences into a later conversation; product claims still require fresh catalog evidence.

The closing message is **Take this retrieval into your own agent**.
Introduce reuse in the opening and connect each lab's repair to the behavior an
agent relies on. Close on an existing checked answer, then show **Download the
skill** (`/api/skill-package`) and **Adapt the implementation**
(`/api/builder-package`). The first provides calling instructions and API
mappings for the running service; the second provides reference SQL and the
implementation map. The full checkout supplies runnable code, evaluations and
citation checks. Participant instructions live in the sibling Workshop Studio
repository.
