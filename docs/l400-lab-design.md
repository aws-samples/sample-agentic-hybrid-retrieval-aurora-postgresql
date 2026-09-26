# Three labs: SQL search to a managed agent

Alex is choosing headphones, a monitor and a chair for his home office. Each lab
extends the previous one. Participants work with the supplied product records
and saved vectors; they do not generate product data or rebuild embeddings.

## Participant work

| Lab | Build | Use it to |
|---|---|---|
| 1 · Retrieve | Restore the close-spelling SQL path and write a vector recall query | Recover Alex's saved Bose listing and compare exact and approximate neighbors |
| 2 · Rank | Implement reciprocal-rank fusion in SQL and evaluate one setting change | Keep the ViewSonic monitor in the shortlist sent to reranking |
| 3 · Build an agent | Assemble a Strands agent, connect its Gateway tools and deploy to Runtime | Compare the monitor and chair, cite a source and respond to a changed requirement |

Labs 1 and 2 use direct `psql` investigations and production search checks. Lab 3
is a practical agent build. Participants complete `create_agent` in
`labs/lab3/agent.py`, add a useful instruction and run `make deploy-agent`.
They do not write tests or a claims query in Lab 3.

## Architecture

Aurora owns products, vectors, hybrid search, fusion, evidence and run records.
Bedrock provides embedding, reranking and answer models. The Strands agent runs
in AgentCore Runtime and calls SQL capabilities through AgentCore Gateway over
MCP. A separate tools Runtime executes the SQL against Aurora in the VPC.
AgentCore Memory is connected with semantic, preference, summary and episodic
strategies; its exercise is optional after the core work.

The environment, services, permissions, catalog and embeddings are prepared.
The participant's deployment packages their agent and their SQL repairs. Source
digests prevent a stale deployed reference from completing the exercise.

## Guide format

Each lab has Scenario and objectives, Architecture and concepts, Tasks,
Conclusion and takeaways, Troubleshooting and Next. Labs 1 and 2 use Observe,
Diagnose, Repair and Prove. Lab 3 uses Connect tools, Build the agent, Deploy and
Use it. Reference explanations stay in collapsible sections.

Errors name the file or command to fix. Completion messages explain what now
works and point to the next action. Hint 4 restores working code; participants
still complete the build's instruction, deployment and product conversation.

## Evidence and acceptance

Lab 1 checks the close-spelling contribution and filters, then independently
computes vector recall. Lab 2 compares participant RRF with an independent
calculation at five values of `k`; the proposed setting is evaluated on judged
queries. These developer checks remain part of the SQL labs.

In Lab 3 the participant observes actual tool calls, opens a cited record and
asks whether a 90W monitor meets a new 100W laptop requirement. The response must
explain the mismatch. A source ID establishes identity; the cited text must
still support the claim.

`make complete-lab-3 RUN_ID=...` checks that actual managed run, current code,
Gateway searches and source records. It saves a receipt without another model
call. Application and release tests remain developer responsibilities; they
are not participant exercises.

## Pacing and release

The source contract allocates 10 minutes to the opening, 10 to Lab 1, 10 to
Lab 2, 20 to Lab 3 including completion, and 10 to optional work. The Introduction
page itself takes about five minutes; opening the prepared tools uses the rest
of the opening block.

Older EC2-only timings do not establish the new managed path's duration. Record
a timed participant rehearsal of deployment, conversation and completion.
Source tests, a live development-account run, a successful Workshop Studio
build and a fresh participant deployment are separate release evidence.
