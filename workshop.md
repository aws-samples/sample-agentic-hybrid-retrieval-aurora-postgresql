# DAT410 Mosaic - Co-Presenter Brief

> Staff brief, written in plain language. It carries no secrets, so it is fine for a participant to find it in Code Editor. Use it to understand the story, divide presenter roles, and answer questions the same way at every table. The operational checklist lives in the Workshop Studio repository's `FACILITATOR_GUIDE.md`; this file does not repeat it.

## The workshop in one minute

Mosaic is a shopping catalog of 500,000 products across consumer electronics, running and fitness, and home office. A shopper can search with keywords or ask in plain language. Both paths run against one Aurora PostgreSQL database, and both can look right while the retrieval behind them is wrong.

Participants repair three deliberate faults in that pipeline, one per lab, and prove each repair from evidence the database records:

1. **Retrieve.** Did the right eligible products enter the candidate pool?
2. **Rank.** Was that pool combined correctly before the reranker touched it?
3. **Reason.** Did the agent's answer cite only evidence the application allowed it to cite?

Every lab uses the same rhythm: **Broken, Diagnose, Fix, Prove.** The fix is small on purpose. The point is the diagnosis and the proof.

The central lesson is:

> Retrieval correctness is a pipeline property, not a top-1 result.

A plausible product card is not proof that search is healthy. A correct final answer is not proof that ranking was correct. Evidence the model has seen is not citable until the application says so.

## What participants do

1. Open three browser tabs from the Event Dashboard: Code Editor and Mosaic, plus the guide itself.
2. In Shop, search `noice cancelng hedfones` and see the Sonora WH-C720 headphones missing. That is the starting fault.
3. Lab 1: reconnect the close-spelling search arm to fusion, in SQL.
4. Lab 2: repair the fusion arithmetic so rank position counts again, in SQL.
5. Lab 3: register retrieved evidence into the application state that authorizes citations, in Python.
6. Run the completion gate, then use the flex time for Vector index at scale, the retrieval scorecard, catch-up, or questions.

Each lab has a manual path and an optional coding-agent path (`claude` from the repository root, with guardrails). Both produce the same small diff and pass the same validator. Each lab also has a five-minute **Fast track** that compresses the implementation, never the proof.

## The participant experience

### Code Editor

A browser VS Code with a terminal already connected to the participant's own Aurora cluster, so `psql` needs no connection string. Participants edit two files across the three labs:

- `db/sql/09_search_functions.sql` for Labs 1 and 2;
- `service/agent_tools.py` for Lab 3.

`uv run python scripts/lab_state.py status` reports each lab as BROKEN or SOLVED. At the start, Lab 1 is BROKEN and Labs 2 and 3 read SOLVED; each later lab resets only its own fault and keeps the repairs already made.

### Mosaic

The customer-facing store, with three surfaces:

- **Shop.** Keyword and filter search over the catalog. Every result card can open "See how this was retrieved", which lands on the Playground with the same query and the same filters.
- **Ask Mosaic.** The agent, in a side panel on Shop. It shows its work: the steps it took, the filters it searched with, the shortlist, the evidence it cited, and what the agent did, tool by tool. Its receipt reads the same way as the Playground's.
- **Playground.** The proof surface, in four numbered stages. This is where the repairs become visible, and where most of the teaching happens.

### The Playground, stage by stage

- **01 Retrieve.** Three ways Aurora looked for the same product: exact terms (full-text search), close spelling (trigram matching), and meaning match (vector similarity). Each shows how many candidates it put in the pool. In the broken Lab 1 state the close-spelling arm reads "not in this pool" while its index is healthy. That contrast is the whole lesson.
- **02 Rank.** One table, one row per result: where each product sat in each arm, its fused position before reranking, its rerank score, and its final position. Select a column heading to read the SQL behind it.
- **Repair evidence.** Paste two persisted run ids to see what a fix changed.
- **03 Reason.** Run the agent on a fixed question and read a six-row chain: products retrieved, evidence returned to the model, evidence registered, evidence authorized, citations resolved, grounded answer. In the broken Lab 3 state the run refuses to answer, and that refusal is correct.
- **04 Prove.** The scorecard, in five plain sections: can search find the right products, did known-good checks still pass, did hard filters hold, did the agent stay inside its evidence rules, and what each ranking step added. Then the package finale: the same capability as a portable skill.

Every number on the Playground is a value the run reported. Nothing is typed in, estimated, or animated for effect.

## The three-lab journey

| Lab | Broken state | Participant lesson | Bounded change | Proof |
|---|---|---|---|---|
| **1 Retrieve** (10 min) | The trigram arm works and returns product 2 at rank 1, but its rows never join the fusion query, so an all-misspelled search cannot find the Sonora WH-C720. | A healthy component inside a broken composition. Recall before ranking: a reranker cannot recover a candidate that never entered the pool. | Restore the `typo` CTE in `search_hybrid_rrf` and add its rows to the channels union. Nothing else changes. | The same request returns product 2 with a trigram rank, and the Lab 1 validator passes. Golden case G-003. |
| **2 Rank** (10 min) | Fusion gives every rank the same contribution, so the wrong chair leads the fused order. The reranker then quietly puts the right chair first, hiding the defect. | A correct answer is not proof of a correct pipeline. Keep the pre-rerank order and every per-arm contribution visible. | Restore a contribution that decreases as rank increases, `1 / (k + rank)`, in the marked formula. | Product 370002 is first both before and after reranking, with correct per-arm contributions. Golden case G-008. |
| **3 Reason** (15 min) | The evidence tool returns records to the model, but the application never registers them, so synthesis refuses to cite anything and the run fails closed. | Evidence seen is not evidence citable. The model requests; the application decides what may reach the answer. | Attach each returned evidence record to application state, keyed by product, in the marked block of `get_product_evidence`. | The agent returns a cited comparison and every citation resolves to a real evidence record. Golden case G-021. |

The starting fault in each lab is intentional. Do not "fix" it before the lab, and do not describe the Lab 3 refusal as an outage.

## How to read the proof

Read a Playground run in this order, top to bottom:

1. The channel list in Retrieve: which arms contributed, and which index served each one.
2. The figures row: candidate pool size, rows returned, and the filters applied.
3. The Rank table: before-reranking position against final position, per row.
4. The Reason chain: six rows, each naming the field it was read from.
5. The receipt band at the bottom of Rank or of an Ask Mosaic answer: filters, candidates found, before reranking, final position, evidence records, time.

Keep three questions separate, because the scorecard keeps them separate:

- **Did anything we depend on stop working?** The known-good checks.
- **How good is ranking across the whole test set?** Recall@10, MRR and nDCG@10 over twenty graded searches, shown with plain labels.
- **Did a hard filter ever leak?** Pass-or-fail checks, never averaged in.

The step-by-step comparison in section E is measured, and it is honest: combining the three arms adds a lot; reranking adds little on this set and costs some recall. Say that plainly if asked. It is the workshop's own data.

## Architecture and authority

Use this plain-language sequence:

1. The shopper's words and filters arrive as one request.
2. Aurora runs three searches in parallel, each applying the same eligibility filters before any limit.
3. Reciprocal rank fusion combines the three position lists into one bounded candidate pool.
4. Cohere Rerank on Amazon Bedrock reorders that pool. It cannot add to it.
5. Every run is written to Aurora with an id, so it can be read back and compared later.
6. For Ask Mosaic, a Strands agent on Amazon Bedrock plans focused searches and may call five typed, read-only tools.
7. The application, not the model, decides which evidence may be cited. If nothing qualifies, there is no answer of record.

The ownership line to repeat: Aurora owns retrieval truth, Bedrock models provide intelligence, and the application owns execution and citation authority. No AgentCore resource is deployed by this workshop.

Models pinned for the event: Cohere Embed v4 for embeddings, Cohere Rerank 3.5 for reranking, Claude Sonnet 4.6 for the agent and synthesis.

## Suggested room flow

| Time | Room activity | Checkpoint |
|---|---|---|
| 0:00 to 0:10 | Framing, open the three tabs, run the misspelled search in Shop | Both URLs load and Lab 1 reads BROKEN |
| 0:10 to 0:20 | Lab 1 Retrieve | Product 2 returns with a trigram rank; validator passes |
| 0:20 to 0:30 | Lab 2 Rank | Product 370002 leads before and after reranking; validator passes |
| 0:30 to 0:45 | Lab 3 Reason | The refusal becomes a cited answer; every citation resolves |
| 0:45 to 0:50 | Completion gate and takeaways | All three validators pass; the guide marks DONE |
| 0:50 to 1:00 | Flex: Vector index at scale, scorecard, catch-up, or questions | Nothing required here |

The hands-on path must reach its last proof at minute 45. The two-minute recovery buffer is part of the 60, not spare lab time. If a table is behind, point them at the lab's Fast track immediately rather than at the end.

## Flex time

The last ten minutes are unstructured. Vector index at scale, the scorecard, catch-up and questions come first. The beats below are what to reach for after those, or when a table finished early. Nothing here is required, nothing here is a fourth lab, and no AgentCore resource is deployed by this workshop. Treat each one as something to say and show from your own screen.

### Observability without moving the ledger

Aurora is the ledger. Every run, candidate, evidence record and citation is persisted there with an id, and every Playground panel reads those rows back. Amazon Bedrock AgentCore Observability receives an aggregate projection of the same run: stage timings, candidate counts, rerank and completion status, model and token metadata, and correlation ids. It carries no product ids, no evidence text, and by default no prompt or answer content, so it holds strictly less than Aurora does and cannot become a second source of truth. It is off by default. A facilitator who wants to show it installs the optional exporter with `uv sync --extra agentcore-observability` and sets `MOSAIC_AGENTCORE_OBSERVABILITY=true`. The repository ships the AWS Distro for OpenTelemetry path for that; the application configures no exporter of its own, so where spans go is an operator choice. With the flag off, or with no recording provider installed, the adapter does nothing and Aurora telemetry is unchanged. The contract is `docs/telemetry-contract.md`, the code is `service/telemetry.py` and `service/telemetry_contract.py`.

### The same process on AgentCore Runtime

The same FastAPI and Strands process participants are running serves on Amazon Bedrock AgentCore Runtime behind a two-route adapter: `deploy/agentcore/app.py` mounts the service whole and adds only `GET /ping` and `POST /invocations`, the routes Runtime checks and calls. The service itself is unchanged, because the evidence authority is Aurora and not the harness. Moving where the agent loop executes does not move the ledger, the retrieval scope, or the rule about what may be cited; the same run ids come back out of the same database. If the event account has a pre-provisioned endpoint, that is a facilitator call-out, not a participant step, and no lab depends on it. The container and the adapter are in `deploy/agentcore/`; the configuration the runtime needs is documented in `docs/agentcore-runtime.md`. No image has been built or deployed from this repository yet.

### What this runs on

`docs/postgres-18.md` collects the version facts for the cluster behind the session: Aurora PostgreSQL 18.3, pgvector 0.8.1, the three retrieval arms and their indexes, iterative index scans on the vector arm, and how a plan receipt is captured for one persisted run. It makes no claim that one PostgreSQL version is faster than another, because nobody has measured that on this corpus. Neither should you at the table.

### The gate is not the guard

For "could a managed gateway do the authorization for us", the appendix at the end of `docs/mcp-interoperability.md` is the answer to read out. An AgentCore Gateway would authenticate callers and publish the three MCP tools, and it would still not decide which evidence an answer may cite. That decision is the one participants just built in Lab 3.

## Speaker roles

### Lead presenter

Own the customer story, pacing, transitions and the closing line. Keep asking:

- What did the shopper see?
- Why is seeing the product not enough to call retrieval healthy?
- Which of the three questions does this proof answer?

### Technical co-presenter

Own the diagnosis, the bounded change and the Playground read. Keep asking:

- Which arm contributed, and which stayed silent?
- Where did this product sit before reranking?
- Did the application register the evidence, or only the model see it?

### Workshop support

Own the tabs, the Code Editor terminal, syntax recovery and the validators. Help participants reach the proof without weakening a rule, creating a local database, or treating a facilitator's screen as their evidence.

## Support guidance

- If a URL fails or the lab state is wrong at the start, stop and escalate. Do not begin a lab on a failed dependency.
- If the API stops answering, restart it and check health from the terminal:

  ```bash
  sudo systemctl restart mosaic-api mosaic-ui
  curl -fsS http://127.0.0.1:8000/api/health
  curl -fsS http://127.0.0.1:8000/api/readiness | jq .
  ```

- "The Mosaic API AWS session has expired" on the Playground means the credentials on the box lapsed. Refresh them and restart the API. Do not swap models or broaden IAM at the table.
- A Playground run that says "not in this pool" beside a healthy index is the Lab 1 lesson, not a bug.
- An Ask Mosaic answer marked "No evidence cited", or an HTTP 503 in Lab 3, is the fail-closed state working. It becomes a cited answer after the repair.
- A question naming something the catalog does not carry is the other case, and it is not a failure. The agent answers with HTTP 200 and an answer of record that declines, naming the terms nothing in the catalog matched. Keep the two apart at the table: a 503 means the pipeline is broken, a decline means the catalog does not hold what was asked for. Nothing needs repairing in the second case.
- If a validator fails after an edit, look only at the marked seam in the one named file. Help with syntax, then ask the participant to explain the rule they restored.
- A lab reset restores the other two repairs on purpose, so only the selected fault is in play. Nothing a facilitator shows counts as a participant pass.
- Never create a local database, switch to fixtures, rebuild an index, or edit retrieval configuration to get past a problem.

## What staff should remember

- The all-misspelled search is not a semantic-search success. Full-text search returns nothing, vector search returns a plausible pool without the target, and only the restored trigram arm finds it.
- Filters are applied inside every search arm before any limit. They are never a reranker hint.
- Raw full-text, trigram, vector, fusion and rerank scores do not share a scale. That is why fusion uses positions.
- The reranker receives a bounded pool. It does not replace retrieval.
- The agent is one bounded Strands agent with five typed, read-only tools. It does not delegate, remember across visits, or traverse a graph.
- Mosaic's memory is Aurora. Every run, candidate, evidence record and citation is persisted with an id. Nothing remembers a shopper between visits, and the Reason stage says so in a footnote.
- Any harness that speaks MCP can call the same three tools with the same contracts. That is the answer to "does this only work with Strands".

## Words to use

Use the shopper's words first and the mechanism second, the way the Playground does.

| Say | It means | Avoid |
|---|---|---|
| Exact terms | PostgreSQL full-text search | FTS, lexical arm |
| Close spelling | `pg_trgm` trigram matching | fuzzy arm, trigram channel |
| Meaning match | pgvector similarity over an HNSW index | semantic arm, dense retrieval |
| Filters | eligibility applied inside each arm | gates, predicates |
| Before reranking | the fused position | RRF rank, fused rank |
| Final position | the served position | rerank rank |
| Evidence record | a product-owned spec or review row with a source and revision | evidence id, provenance |
| Known-good checks | the fixed behaviors the labs depend on | golden anchors, regression anchors |
| Step-by-step comparison | one ranking step changed at a time | ablation |
| Where these numbers come from | which code version was measured | provenance, attribution |

## Before the session

Follow the event-owner preflight in the Workshop Studio repository's `FACILITATOR_GUIDE.md` end to end in a fresh event account. The steps most often skipped, and most expensive to skip:

- confirm the account can invoke all three pinned models;
- confirm readiness reports 500,000 products and 500,000 embeddings;
- confirm Lab 1 reads BROKEN and Labs 2 and 3 read SOLVED;
- seed the HNSW exact ground truth, which the cached bootstrap does not do and which Vector index at scale needs to render at all;
- run all three labs and the completion gate yourself from the rendered guide.

Beyond the guide, keep at least one replacement event account available. A broken account gets replaced; nobody improvises infrastructure at the table.

## Closing script

Lab 1 taught us that a healthy component can sit inside a broken pipeline, and that recall comes before ranking.

Lab 2 taught us that a correct answer is not proof of a correct pipeline, so ranking has to stay inspectable.

Lab 3 taught us that evidence the model has seen is not evidence it may cite, and that the application decides.

The method is:

> Find the arm that stayed silent, repair the smallest seam, run the same request again, and prove it from what Aurora recorded.

Then send them to the Prove stage: the scorecard is the same measurement on the same database, and it is theirs to take home.
