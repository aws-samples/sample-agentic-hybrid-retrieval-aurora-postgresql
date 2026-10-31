# Three labs: SQL search to a managed agent

Alex is choosing headphones, a monitor and a chair for his home office. Each lab
extends the previous one. Participants work with the supplied product records
and saved vectors; they do not generate product data or rebuild embeddings.

## Participant work

| Lab | Build | Use it to |
|---|---|---|
| 1 · Retrieve | Restore the fuzzy matching SQL path (a vector recall query is optional) | Recover Alex's saved Logitech listing and compare exact and approximate neighbors |
| 2 · Rank | Implement reciprocal-rank fusion in SQL and evaluate one setting change | Keep the ViewSonic monitor in the shortlist sent to reranking |
| 3 · Build the Retrieval agent | Assemble the Retrieval agent, connect its Gateway tools and deploy to Runtime | Compare headphones, monitor and chair, cite each product’s sources and respond to a changed requirement |

Labs 1 and 2 use direct `psql` investigations and production search checks. Lab 3
is a practical Retrieval agent build. Participants complete `create_agent` in
`labs/lab3_reason/agent.py`, add a useful instruction and run `uv run python scripts/deploy_agentcore.py deploy`.
They do not write tests or a claims query in Lab 3.

## Architecture

Aurora owns products, vectors, hybrid search, fusion, evidence and run records.
Bedrock provides embedding, reranking and answer models. The Retrieval agent runs
in AgentCore Runtime and calls SQL capabilities through AgentCore Gateway over
MCP. A separate tools Runtime executes the SQL against Aurora in the VPC.
AgentCore Memory is connected with semantic, preference, summary and episodic
strategies; its exercise is optional after the core work.

The environment, services, permissions, catalog and embeddings are prepared.
The participant's deployment packages their agent and their SQL repairs. Source
digests prevent a stale deployed reference from completing the exercise.

## Guide format

Each lab has a Concepts page and an Exercise page. The Exercise page has four
verb-led sections that follow Broken, Diagnose, Fix and Prove, then Running
behind. Required steps state the command or edit, what to inspect and how to prove it.
Reference explanations and optional extensions stay in collapsible sections;
the lab READMEs are reminders, not a second full walkthrough.

Errors name the file or command to fix. Completion messages explain what now
works and point to the next action. Hint 4 restores working code; participants
still complete the build's instruction, deployment and product conversation.

## Evidence and acceptance

Lab 1 checks the fuzzy matching contribution and filters. Its optional vector
recall exercise computes exact neighbors independently. Lab 2 compares participant RRF with an independent
calculation at five values of `k`; the proposed setting is evaluated on judged
queries. These developer checks remain part of the SQL labs.

In Lab 3 the participant observes actual tool calls, opens a cited record and
asks whether a 90W monitor meets a new 100W laptop requirement. The response must
explain the mismatch. A source ID establishes identity; the cited text must
still support the claim.

`uv run python scripts/grade_setup_run.py` checks the newest managed setup run, current code,
Gateway searches and source records. It saves a receipt without another model
call. Application and release tests remain developer responsibilities; they
are not participant exercises.

## Pacing and release

The source contract allocates 15 minutes to orientation (a 10-minute presenter
introduction, then 5 to open the prepared tools through Getting started), 10 to
Lab 1, 10 to Lab 2, 20 to Lab 3 including completion, and 5 to wrap-up and
questions. Optional exercises are untimed.

Older EC2-only timings do not establish the new managed path's duration. Record
a timed participant rehearsal of deployment, conversation and completion.
Source tests, a live development-account run, a successful Workshop Studio
build and a fresh participant deployment are separate release evidence.
