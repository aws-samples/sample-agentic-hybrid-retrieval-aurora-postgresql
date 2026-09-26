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
- **Reason:** can synthesis cite only evidence attached to the answer's citation
  scope?

## Session flow

`data/evals/mosaic_labs_missions.json` is the source for every timing below.
`make validate-missions` fails if the 60-minute budget or a live target drifts.

| Time | Stage | Required outcome | Stable eval anchors |
|---:|---|---|---|
| 0-10 min | Introduction / Overview / Presentation | Meet Alex, frame the three lessons and architecture | `typo-recovery` before repair |
| 10-20 min | Retrieve | Reconnect one candidate arm and prove target recovery without weakening eligibility | `typo-recovery`, with control anchors |
| 20-30 min | Rank | Repair one RRF formula and keep the suitable monitor inside the reranker input | `rank-with-evidence`, with control anchors |
| 30-50 min | Reason | Attach evidence identity to synthesis state, prove citation scope and run the completion gate | `agentic-research`, with one evidence control |
| 50-60 min | Flex | Use one optional lab, recover, or take questions | n/a |

The stable IDs remain evaluation identifiers and starter-gap ownership keys.
They are checkpoints inside three labs, not participant navigation.

### Where the required path lives in the shipped app

Opening the Playground (the header's third link, `/labs/retrieval` with no
saved Shop search) leads with a "Required workshop path" panel: the three lab
titles in order, each one's live repair state from `GET /api/labs/state`, and
one action into the lab that still needs it -- "Start Lab 1" before anything is
touched, "Continue Lab 2" or "Continue Lab 3" once the labs in front of it are
repaired, "Review your labs" once all three are. Alex's other requests below it,
Scale & HNSW, and Session & Memory are named as optional in the same panel; a
participant can finish the required sequence without opening any of them.
Inside a lab, `LabRail` keeps the same three facts in view: which lab, which of
its four stages (Retrieve, Rank, Reason, Prove) is current, and the file the
repair belongs in. Completion is never inferred from having visited a page --
only `POST /api/labs/{id}/proof`, run from the Prove stage, can mark a lab
passed.

## Lab 1 - Build hybrid retrieval

Goal: construct the right candidate universe before deciding the winner.

1. Save the transposed-ID failure and propose a falsifiable cause.
2. Compare the three installed search methods with the recorded filters and
   limits in `psql`. Inspect a selective vector scan with `EXPLAIN (ANALYZE,
   BUFFERS, SETTINGS)` at two transaction-local settings, including the eligible population.
3. Repair the connection the evidence identifies, then repeat the identical
   request. Prove that only the declared method recovered this target.
4. Run exact-ID and eligibility controls. Distinguish target recovery, returned
   row count and recall against an independently known correct set. Never
   promise that changing scan memory must change the result.

Required concepts:

- `tsvector`, `tsquery`, and PostgreSQL full-text search;
- `pg_trgm` similarity for typo recovery;
- pgvector HNSW semantic retrieval;
- relational and metadata predicates;
- exact identity, eligibility, and candidate provenance.

Do not turn this into a `pg_trgm` lesson. The transposed listing ID is
deliberately not presented as an embeddings success. On the measured
500,000-product corpus, HNSW returns related listings but not the target.
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

The 27-inch 4K/90W request gives a visible before/after: Dell U2720Q is
missing from the broken pool and enters after repair. It then rises from
combined position 24 to final position 1 in repeated verification. HP Z27n's
1440p title is a clear contrast. Inspect actual ranks on the participant run;
position 24 and final position 1 are observations. The mission permits a final
top-three position; managed-model exact order is not the correctness contract.
The terminal runner rejects changed queries, filters, settings or datasets and
checks absence from the full before pool and presence after. In `psql`, builders
join the saved runs and call the installed contribution function at half, recorded
and double k. Participants explain head/tail preference and recorded reranking
time; this arithmetic study does not establish which setting gives best relevance.

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
tools, candidates, and records inside the answer's citation scope produced the
recommendation. The completion gate also requires two distinct focused searches:
one retrieval receipt must cover the chair target and another must cover the
monitor target. A single broad search cannot satisfy decomposition.

The implementation is intentionally narrow: one Strands agent, a bounded tool
budget, one repair attempt after invalid synthesis, and no delegation or
multi-hop graph traversal. Closed-world follow-ups can reuse a server-validated
prior shortlist, but every answer still retrieves fresh evidence and passes the
same citation checks.

The required citation challenge uses freshly resolved records as a positive
control, then changes the evidence ID, quote and revision in memory. It also
executes the production named-product citation guard with the other product's
record. No database record is changed. This checks specific failure modes,
not general semantic truth. The final brief returns to all three items:
headphones, the recovered monitor and a wheeled chair, with unknown microphone
performance, laptop compatibility and personal comfort stated separately.

## Prove (unnumbered finale)

Prove is included inside Lab 3's 20-minute budget, not an additional lab.
Run the three validators, inspect a saved plan, and resolve citations from the
monitor/chair answer and the headphone evidence control. The required path
contains three repairs and five controls. A separate representative evaluation
is needed to make whole-catalog ranking claims.

## Shared receipt vocabulary

Every stage uses the same compact reading order:

```text
filters -> candidates by arm -> fused rank -> rerank -> evidence IDs -> latency
```

Search receipts leave evidence IDs empty because synthesis has not run. Agent
receipts add evidence IDs and tool latency. Participants learn one diagnostic
vocabulary rather than three unrelated troubleshooting workflows.

## Build-and-wire extension

[Build a retrieval tool](build-retrieval-tool.md) adds a participant-owned tool
on top of the solved pipeline. Generate a starter, implement the headphone
eligibility rule, register the typed tool, and run the live API checker with two
budgets. Then let the configured Bedrock agent invoke it. This fits flex time or
continues after the session; the three required lab contracts stay unchanged.
The [adaptation guide](use-in-your-app.md) maps every abstract promise to its
working schema, SQL or application file.

The main Playground also offers Plan my workspace (the canonical Lab 3 request)
and Check the sources (specification versus sample review evidence). The latter
shows retrieved records even when the answer does not cite them.

## Advanced Labs (OPTIONAL)

Optional work does not consume the required 40-minute three-lab path or the
completion proof inside Lab 3:

1. Tune the HNSW operating point with recall, latency, plans, filter
   selectivity, and iterative scans.
2. Run retrieval evaluation and failure analysis using the existing eval
   infrastructure.
3. Use the troubleshooting runbook for Aurora, services, source state, and
   Bedrock model access.

MCP interoperability and AgentCore remain a short productionization reveal,
not a fourth lab. The repository proves shared tool version, output
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
3. The application owns execution and citation scope: which retrieved evidence
   may enter synthesis.
4. AgentCore can own managed runtime, transport, and tool exposure without
   becoming the retrieval authority.

Then distinguish three evaluation questions in under 90 seconds:

- golden anchors: did critical behavior regress?
- an independently judged current-catalog sample: how good is retrieval?
- current-catalog filter checks: did eligibility violate a contract?

The historical 20-query ranking population and 720 synthetic cases remain archived
measurements. Neither certifies the imported dataset. See the measured
[example library](real-catalog-exercise-library.md) for the broader teaching set.
