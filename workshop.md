# DAT410-R Mosaic — Presenter brief

Help Alex choose headphones, a monitor and a chair for his home office.
Participants repair SQL retrieval and ranking, then build a Strands agent that
uses that SQL to answer with sources. Follow the participant's Workshop Studio
guide; it keeps required actions visible and reference material collapsed.

The operational preflight and publication gates live in the Workshop Studio
repository's `FACILITATOR_GUIDE.md`. Use the [setup guide](docs/workshop-studio-setup.md)
for both repositories and the [publishing runbook](docs/workshop-studio-publishing.md)
for release work. This brief is for delivery, not a second runbook.

## Run the hour

| Time | Work | Evidence to inspect |
|---|---|---|
| 0–10 | Introduction and prepared tools | Alex's need, one saved search and the three search methods |
| 10–20 | Lab 1 — Retrieve | The missing listing returns through close spelling; filters hold |
| 20–30 | Lab 2a — Rank; Lab 2b — Re-rank | Contributions vary with position; judged comparisons support a tuning decision |
| 30–50 | Lab 3 — Reason, including completion | Three focused searches, comparison, sources, changed requirement and original-run proof |
| 50–60 | Optional work, recovery or questions | One retrieval-tool or HNSW exercise if time permits |

The [mission manifest](data/evals/mosaic_labs_missions.json) owns the timing,
exact requests, filters, targets and assertions. Protect its **40-minute
hands-on budget**. Completion is inside Lab 3; Memory is after the required hour.
These are planned allocations, not measured human completion times.

Assign a lead for the clock and story, a SQL presenter, an agent presenter and
room support. One person may cover several roles; keep the staffing roster
outside the repository. Avoid extra demonstrations during a lab's proof time.

## Open with the customer

> Alex needs headphones for focus and calls, a monitor for code and documents,
> and a chair for long days. We have over half a million product listings in
> Aurora. Can we find suitable products, rank them, and support each recommendation?

Show the correctly spelled headphone request, then the guide's transposed ID
with the same filters. A full result list can omit the intended product.
Ask where it disappeared; let the lab establish the cause.

Point participants to the Event Dashboard's **CodeEditorURL** and **MosaicURL**.
Code Editor opens **Start Here**, a prepared terminal and the numbered lab views:
**01 — Retrieve**, **02 — Rank & Re-rank**, **03 — Reason**. **04 — Explore
Mosaic source** contains application files and `learning-notes.md`; maintainer
files and reference answers are hidden. These views use the same files and paths.
The default theme is **Dark Modern**.

## Lead each lab

Every lab follows **Broken → Diagnose → Fix → Prove**. Ask for a prediction
before hints. Keep the original request, inspect the mechanism, repair only the
marked block, apply/deploy, then repeat and explain the result.

### Lab 1: candidate membership

Follow the guide's three typo searches. Run each production search separately
in `psql`; find the method whose candidates never reach fusion. Participants
repair only `LAB1_CHANNEL` in `labs/lab1_retrieve/hybrid_search.sql`.

After applying SQL, inspect the intended listing's close-spelling rank and
contribution. The correct-ID and brand/category controls must still pass.
Another listing of the same model is not the requested identity. Reranking
cannot recover a product it never receives. The vector recall query is optional.

### Lab 2: contributions and admission to reranking

In **2a — Rank**, inspect saved source positions and contributions. When every
position earns equal credit, ties let product IDs decide the cutoff. Participants
repair only `LAB2_RRF_FORMULA` in `labs/lab2_rank/rrf_contribution.sql`.

In **2b — Re-rank**, repeat the request and run the exercise check. Inspect the
monitor's source position, combined position and final position in that order.
Read the participant's actual ranks; do not demand a particular measured example.

Run the judged-query comparison and ask which setting they would ship and why.
Count improvements and regressions, read the sign test, and keep the reranker
budget in view. The comparison changes no served setting. Optional weighted RRF
comes after completion. A plausible winner does not prove fusion worked.

### Lab 3: build, deploy and use the agent

Discover Gateway tools, then complete `create_agent` inside `LAB3_AGENT` in
`labs/lab3_reason/agent.py`. Participants keep the supplied model, tools, source
rules and hooks, and add one instruction of their own. Deploy using the guide.

Run **Playground → Complete my room → Reason**. Save the original run ID. Ask Mosaic
opens from the **Ask Mosaic** pill in the header on every page. The
Ask Mosaic **Complete my room** starter is available before and after the agent is
built and runs on its own filters; it shows "Shop filters were cleared for this lab
request." when it replaces filters a participant had set. A follow-up question is
not graded against the lab. The Prove page's **Maintainer measurements** are
collapsed saved results for facilitators and do not grade a participant. Ask Mosaic's **Builder view** switch shows a run's recorded steps and per-search ranks, from the saved searches, when a participant needs to inspect an answer.
Inspect separate searches for the headphones, monitor and chair; all three in
the comparison and final shortlist; their supporting citations; and a ranking
explanation. Open the chair's listing and review: adjustable features and one
person's comfort experience make different claims. Check microphone evidence
separately from listening noise cancellation.

Ask the guide's changed 100W requirement against the monitor's 90W record.
The agent must acknowledge the mismatch and any unknown compatibility.
Prove the **original room run**, then finish the Conclusion checks. Completion
reuses the saved answer; a deployed endpoint alone is not a participant pass.

## Keep the architecture explanation short

Aurora owns products, vectors, eligibility filters, fusion, source evidence and
run records. Bedrock supplies embeddings, reranking and the answer model.
AgentCore Runtime hosts the Strands agent and SQL tool service; AgentCore Gateway
connects them over MCP. Both are required for Lab 3 and provisioned by the workshop.

The application constrains tool calls and checks citations. Registering a source
allows its citation; it does not establish that every sentence follows from it.
Specifications, reviews and unknowns remain distinct. Catalog-read-only tools
still write search audit records.

Memory supplies optional conversation context, never current product facts.
Saving a message does not prove an extracted preference exists; wait for its
record. **New session** keeps the user, while **Start fresh** changes identity.
The guide includes current-request priority and isolation checks.

For deeper questions, use [architecture](docs/architecture.md),
[fusion and reranking](docs/fusion-rerank.md), [managed deployment](docs/agentcore-runtime.md),
[source checks](docs/security-boundaries.md) and [MCP integration](docs/mcp-interoperability.md).
Optional observability export remains separately subject to runtime verification.

## Help without erasing the exercise

- Inspect the saved result, lab state and diff first. Coding help starts with
  the current lab's Hint 3 and stays within its marked block.
- Start resumes safely after interruption. Reset discards only the selected
  lab's edits. Hint 4 restores the reference repair; apply/deploy and proof still follow.
- A file edit does not update Aurora or Runtime. If results are stale, use the
  guide's apply/deploy command, repeat the request and inspect the new record.
- Environment failures go to room support with the failing command and redacted
  error. Use the facilitator runbook; do not improvise infrastructure at the table.
- Preserve filters, retrieval settings, indexes, source checks and participant
  notes. Use Aurora only. Never substitute a facilitator's run for participant proof.

## Close on the evidence

Ask each participant to name one supported claim and one unresolved question
for each of Alex's three picks. Finish the guide's completion check before optional work.

> Find the missing candidates, make their positions count, then check the
> sources behind the answer.

Before the event expires, use **Take this retrieval into your own agent** in
Playground: **Connect retrieval tools**, **Download the skill**, and **Adapt the
implementation**. The skill guides a running backend; it does not host the
catalog or replace service permissions. Follow the
[adaptation guide](docs/use-in-your-app.md) for another domain.

Consult [READINESS.md](READINESS.md) for release evidence. Offline tests, live
development checks, a successful Studio build and a fresh-account rehearsal
prove different things. None substitutes for human timing or physical display checks.
