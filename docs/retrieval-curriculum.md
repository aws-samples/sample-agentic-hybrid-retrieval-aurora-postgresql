# Builder-session curriculum

## Session promise

Attendees build one retrieval system in three stages:

```text
RETRIEVE -> RANK -> REASON
```

Aurora PostgreSQL first constructs the right candidate universe, then produces
an inspectable final order, then exposes those capabilities to a retrieval
agent. The agent orchestrates the system; it does not replace it.

## Session flow

`data/evals/mosaic_labs_missions.json` is the source for every timing below.
`make validate-missions` fails if the 60-minute budget or a live target drifts.

| Time | Stage | Required outcome | Stable eval anchors |
|---:|---|---|---|
| 0-8 min | Getting started | Architecture, Mosaic, and the baseline failure are visible | `typo-recovery` before repair |
| 8-22 min | Retrieve | Build hybrid retrieval and prove typo recovery, exact identity, and eligibility | `typo-recovery`, `exact-identity`, `semantic-eligibility` |
| 22-37 min | Rank | Repair RRF, rerank, inspect provenance, and explain why result 1 beat result 2 | `rank-with-evidence` |
| 37-53 min | Reason | Attach retrieved evidence to synthesis and produce a grounded cited recommendation | `agentic-research` |
| 53-58 min | Wrap-up | Run the scorecard and recap the architecture | all required checks |
| 58-60 min | Recovery buffer | Absorb a transition or rerun a failed checkpoint | n/a |

The stable IDs remain evaluation identifiers and starter-gap ownership keys.
They are checkpoints inside three labs, not participant navigation.

## Lab 1 - Build hybrid retrieval

Goal: construct the right candidate universe before deciding the winner.

1. Run the misspelled request and expose the disconnected `pg_trgm` arm.
2. Restore trigram participation in unweighted RRF.
3. Prove exact identity still survives through PostgreSQL full-text search.
4. Use HNSW to expand semantic intent.
5. Apply SQL and JSONB constraints inside every candidate arm.
6. Inspect FTS, trigram, and semantic provenance independently.

Required concepts:

- `tsvector`, `tsquery`, and PostgreSQL full-text search;
- `pg_trgm` similarity for typo recovery;
- pgvector HNSW semantic retrieval;
- relational and metadata predicates;
- exact identity, eligibility, and candidate provenance.

The all-misspelled query is deliberately not presented as an embeddings success.
On the measured 500,000-product corpus, HNSW returns plausible headphones but
not the target; FTS and trigram recover it.

## Lab 2 - Fuse, rerank, and explain

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

## Lab 3 - Build the retrieval agent

Goal: give the inspectable retrieval system to a bounded agent.

The working contracts remain:

- `search_products`;
- `get_product_evidence`;
- `compare_products`;
- `explain_retrieval`;
- `synthesize_cited_answer`.

The participant restores the five-line evidence-state boundary. The agent then
decomposes the compound request, performs targeted retrieval, preserves hard
constraints, compares retrieved evidence, and synthesizes a cited answer. The
trace, persisted retrieval-run IDs, and resolvable evidence IDs prove which
tools, candidates, and records produced the recommendation.

## Advanced Labs (OPTIONAL)

Optional work does not consume the required 45-minute hands-on path:

1. Tune the HNSW operating point with recall, latency, plans, filter
   selectivity, and iterative scans.
2. Run retrieval evaluation and failure analysis using the existing eval
   infrastructure.
3. Use the troubleshooting runbook for Aurora, services, source state, and
   Bedrock model access.

MCP interoperability remains supported reference material. It is not a fourth
required lab.

## Final production lesson

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
