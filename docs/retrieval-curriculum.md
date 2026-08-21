# Builder-session curriculum

## Session promise

Attendees repair one retrieval system in three stages:

```text
RETRIEVE -> RANK -> REASON
```

The thesis is **retrieval correctness is a pipeline property, not a top-1
result**. Aurora PostgreSQL first constructs the eligible candidate universe,
then produces an inspectable order, then exposes those bounded capabilities to
a retrieval agent. Every lab is a composition failure while the component
inside the broken boundary still works:

- **Retrieve:** did the right eligible candidates enter the pool?
- **Rank:** was that pool combined correctly before reranking?
- **Reason:** can synthesis use only evidence the application authorized?

## Session flow

`data/evals/mosaic_labs_missions.json` is the source for every timing below.
`make validate-missions` fails if the 60-minute budget or a live target drifts.

| Time | Stage | Required outcome | Stable eval anchors |
|---:|---|---|---|
| 0-10 min | Introduction | Frame the pipeline thesis, open Mosaic, and capture the baseline | `typo-recovery` before repair |
| 10-20 min | Retrieve | Reconnect one candidate arm and prove candidate recall without weakening eligibility | `typo-recovery`, with control anchors |
| 20-30 min | Rank | Repair one RRF formula and prove why final rank masked it | `rank-with-evidence`, with control anchors |
| 30-45 min | Reason | Attach evidence identity to synthesis state and prove citation authorization | `agentic-research`, with one evidence control |
| 45-50 min | Conclusion | Run the completion gate and separate regression, quality, and contract evaluation | all required checks |
| 50-60 min | Flex | Use one optional lab, recover, or take questions | n/a |

The stable IDs remain evaluation identifiers and starter-gap ownership keys.
They are checkpoints inside three labs, not participant navigation.

## Lab 1 - Build hybrid retrieval

Goal: construct the right candidate universe before deciding the winner.

1. Run the misspelled request and expose the disconnected `pg_trgm` arm.
2. Restore trigram participation in unweighted RRF.
3. Repeat the identical request and prove trigram rank and contribution returned
   while exact identity and eligibility still hold.
4. Spend 60-90 seconds reading the production plan: confirm the installed HNSW
   path and the bounded semantic candidate pool. Do not rebuild an index.

Required concepts:

- `tsvector`, `tsquery`, and PostgreSQL full-text search;
- `pg_trgm` similarity for typo recovery;
- pgvector HNSW semantic retrieval;
- relational and metadata predicates;
- exact identity, eligibility, and candidate provenance.

Do not turn this into a `pg_trgm` lesson. The all-misspelled query is
deliberately not presented as an embeddings success. On the measured
500,000-product corpus, HNSW returns plausible headphones but not the target.
The question participants must answer is: **why is seeing the correct product
not enough to declare retrieval healthy?**

## Lab 2 - Fuse, rerank, and inspect

Goal: put the right candidates in the right order without hiding the ranking
decisions.

```text
FTS --------\
pg_trgm -----+-> RRF -> bounded candidate set -> Cohere Rerank -> final order
HNSW -------/
```

Structured filters remain eligibility gates. They do not become arbitrary
ranking weights.

Attendees repair the actual `1 / (k + rank)` contribution, then retain and
compare:

- lexical, trigram, and semantic rank;
- RRF score and pre-rerank position;
- Cohere Rerank score and final rank;
- candidate counts and persisted retrieval-run evidence;
- product source URI, source revision, and attached evidence.

The B-side replays the same candidate set through historical weighted fusion.
Measured on the live corpus, the weights reorder 243 of 250 candidates for the
lab anchor while the reranker can absorb the difference. The checkpoint asks
why result 1 beat result 2 across stages rather than treating the final score as
an unexplained scalar.

This is the centerpiece. The line to retain is: **a correct answer is not proof
of a correct pipeline.**

## Lab 3 - Build the retrieval agent

Goal: give the inspectable retrieval system to a bounded agent.

The working contracts remain:

- `search_products`;
- `get_product_evidence`;
- `compare_products`;
- `explain_retrieval`;
- `synthesize_cited_answer`.

The participant restores the five-line evidence-state boundary. The model can
request a tool, but the application decides whether it executes. The model can
read returned evidence, but that alone does not make the evidence citable. The
trace, persisted retrieval-run IDs, and resolvable evidence IDs prove which
tools, candidates, and application-authorized records produced the
recommendation.

The implementation is intentionally narrow: one Strands agent, a bounded tool
budget, one repair attempt after invalid synthesis, and no delegation or
multi-hop graph traversal. Closed-world follow-ups can reuse a server-authorized
prior shortlist, but every answer still retrieves fresh evidence and passes the
same citation checks.

## Shared receipt vocabulary

Every stage uses the same compact reading order:

```text
filters -> candidates by arm -> fused rank -> rerank -> evidence IDs -> latency
```

Search receipts leave evidence IDs empty because synthesis has not run. Agent
receipts add evidence IDs and tool latency. Participants learn one diagnostic
vocabulary rather than three unrelated troubleshooting workflows.

## Advanced Labs (OPTIONAL)

Optional work does not consume the required 45-minute hands-on path:

1. Tune the HNSW operating point with recall, latency, plans, filter
   selectivity, and iterative scans.
2. Run retrieval evaluation and failure analysis using the existing eval
   infrastructure.
3. Use the troubleshooting runbook for Aurora, services, source state, and
   Bedrock model access.

MCP interoperability and AgentCore remain a short productionization reveal,
not a fourth required lab. The repository proves shared tool version, output
schema, and read-only policy for `search_products` and
`get_product_evidence`. It does not claim a deployed AgentCore Gateway or
runtime-result parity that the workshop did not measure.

## Final production lesson

The required path captures one persisted retrieval event's production
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)` plan on demand. Participants
connect the FTS and trigram function scans, pgvector HNSW index scan, candidate
caps, joins, runtime settings, and persisted rank receipt rather than treating
Aurora as an opaque store behind the agent.

The winning architecture is not "vector search." It is a controlled retrieval
system:

```text
query understanding
  -> lexical / typo / semantic candidate generation
  -> relational eligibility filters
  -> reciprocal-rank fusion
  -> model reranking
  -> evidence + source attribution
  -> typed agent tools
  -> cited answer
```

Close with four ownership rules:

1. Aurora owns retrieval truth: candidates, filters, indexes, fusion, rank
   provenance, and evidence.
2. Bedrock models provide intelligence: embeddings, reranking, orchestration,
   and synthesis.
3. The application owns authority: tool execution and the evidence allowed into
   synthesis.
4. AgentCore can own managed runtime, transport, and tool exposure without
   becoming the retrieval authority.

Then distinguish three evaluation questions in under 90 seconds:

- golden anchors: did critical behavior regress?
- the 19-query ranking population: how good is retrieval?
- the 720 filter fixtures: did eligibility violate a contract?
