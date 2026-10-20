# DAT410-R Mosaic — Presenter brief

Help Alex choose headphones, a monitor and a chair for his home office.
Participants repair SQL retrieval and ranking, then build the Retrieval agent, a Strands agent that
uses that SQL to answer with sources. Follow the participant's Workshop Studio
guide; it keeps required actions visible and reference material collapsed.

The operational preflight and publication gates live in the Workshop Studio
repository's `FACILITATOR_GUIDE.md`. Use the [setup guide](docs/workshop-studio-setup.md)
for both repositories and the [publishing runbook](docs/workshop-studio-publishing.md)
for release work. This brief is for delivery, not a second runbook.

## Run the hour

| Time | Work | Evidence to inspect |
|---|---|---|
| 0–15 | Presenter introduction, then prepared tools | Alex's need, one saved search and the three search methods |
| 15–25 | Lab 1: Retrieve - Debug hybrid search | The missing listing returns through fuzzy matching; filters hold |
| 25–35 | Lab 2: Rank and re-rank - Tune rank fusion and reranking | Contributions vary with position; judged comparisons support a tuning decision |
| 35–55 | Lab 3: Reason - Build and deploy the Retrieval agent, including completion | Three focused searches, comparison, sources, changed requirement and original-run proof |
| 55–60 | Wrap-up and Q&A | Questions; Session & Memory, retrieval-tool and HNSW exercises are untimed options |

The [mission manifest](data/evals/mosaic_labs_missions.json) owns the timing,
exact requests, filters, targets and assertions. Protect its **40-minute
hands-on budget**. Completion is inside Lab 3; Memory leads the untimed optional exercises.
These are planned allocations, not measured human completion times.

During setup, use **Getting started** to open Code Editor, run one readiness
query in `psql` and save Lab 1's failing search. Every Getting started step
runs in the terminal; the catalog tour and Mosaic are optional there. Mosaic's first visit to Shop opens a guided tour of its controls
(Next or Skip the tour); the compass in the header replays it. One-time tips then point
at the Playground link after the first Shop search and at the Retrieval agent's button and steps.
Lab 1 starts in `psql` with the request Getting started saved; Shop shows the
same search as an optional check. Lab 2 continues in `psql` with the monitor
request that Lab 1's handoff saved. Its optional Shop check selects Monitor
explicitly, without depending on the participant having visited Shop in Lab 1.
Lab 2 ends with `advance --lab 2`, which proves Lab 2 and installs the
Retrieval agent's starting code. Lab 3 stays in the terminal: deploy, ask the setup
request and the 100W follow-up with `scripts/ask_agent.py`, then complete the
setup run by the Run ID it printed. Ask Mosaic is an optional view of the same runs.

Each lab opens with its time and one command,
`uv run python scripts/lab_state.py finish --lab N`, for anyone who already knows
the lab or is running behind: it installs the reference answer, applies or
deploys it and runs the lab's checks and hand-off. The lab's **Running behind?**
section explains the same command; `reset
--lab N` starts that lab over. Someone who knows the earlier material can start
later from Getting started's **Choose where to start**: `skip-to --lab N`
finishes the earlier labs with their reference answers and leaves lab N's
exercise to do. Lab 3's completion still needs their own setup run, so no one
completes without using the Retrieval agent.

Assign a lead for the clock and story, a SQL presenter, a Retrieval agent presenter and
room support. One person may cover several roles; keep the staffing roster
outside the repository. Avoid extra demonstrations during a lab's proof time.

## Open with the customer

Introduce the central question on the landing page and in the opening talk.
Then follow Alex's progress: find his headphones, rank his monitor, add the
chair and check the whole setup. Each lab opens with what he has achieved and
what he needs next; each handoff carries the participant's repairs forward.

Use the guide's opening order: the landing page's Business challenge and
schedule, then Getting started; the guide's Overview page is optional, since
the talk covers it. The talk names where Labs 1 and 2 break; the labs prove
it: participants inspect their actual result, find the exact mechanism, and
explain what the repair changes for Alex before moving to his next need.

> Alex needs headphones for focus and calls, a monitor for code and documents,
> and a chair for long days. We have over half a million product listings in
> Aurora. Can we find suitable products, rank them, and support each recommendation?

Show the correctly spelled headphone request, then the guide's transposed ID
with the same filters. A full result list can omit the intended product.
Ask where it disappeared; let the lab establish the cause.

After the Lab 1 repair passes validation, keep participants in Lab 1 for the
description search. Use the guide's final `advance --lab 1` command to prepare
Lab 2 only after they have inspected those results.

Point participants to the Event Dashboard's **CodeEditorURL** and **MosaicURL**.
Code Editor opens **Start Here**, a prepared terminal and the numbered lab views:
**01 - Retrieve**, **02 - Rank and re-rank**, **03 - Reason**. **04 - Explore
Mosaic source** contains application files; maintainer
files and reference answers are hidden. These views use the same files and paths.
The default theme is **Dark Modern**.

## Lead each lab

Every lab follows **Broken → Diagnose → Fix → Prove**. Ask what the evidence
shows before giving hints. Keep the original request, inspect the mechanism, repair only the
marked block, apply/deploy, then repeat and explain the result.

### Lab 1: candidate membership

Follow the guide's three typo searches. Run each production search separately
in `psql`; find the method whose candidates never reach fusion. Participants
repair only `LAB1_EDIT` in `labs/lab1_retrieve/hybrid_search.sql`. Search lives
in one schema, `mosaic_search`: the `product_listing` table and its
`product_search_*` indexes, the `product_listing_view` every search reads, and the
functions as the lab files define them, so `\sf mosaic_search.search_hybrid_rrf`
shows exactly what Aurora runs.

After applying SQL, inspect the intended listing's fuzzy matching rank and
contribution. The correct-ID and brand/category controls must still pass.
Another listing of the same model is not the requested identity. Reranking
cannot recover a product it never receives. The vector recall query is optional.

At the end of Lab 1, `uv run python scripts/lab_state.py advance --lab 1`
validates the applied repair and live retrieval controls, saves the passing
evidence, then prepares Lab 2. Run it only after inspecting all Lab 1 examples.
Retries preserve edits and resume any interrupted preparation. Every Lab 1 and
Lab 2 check reads the saved block the same way, so `validate_lab.py` cannot pass
while `advance` refuses. A refusal names the first difference (for example
`column 3 is trigram_score`), the fix and the rerun. Equivalent SQL passes:
column or table aliases and qualified columns. Live-check failures in the
terminal name the
product and search method as Shop does and end in a command or a facilitator
handoff; an apply error names the participant's file and line, and
`uv run python scripts/diff.py` names in plain words the lines of a lab file that
differ from the reference answer, inside and outside the markers, without printing
the answer (`--answer` adds it). A start whose
search already works records that instead of stopping, and repeating a request
without a saved Before shows the search alone. Shop shows symptoms before
diagnosis and does not credit pre-start searches as repairs.
Its ordering control sorts the same displayed products; Playground holds the
full candidate pool.

### Lab 2: contributions and admission to reranking

In **2a — Rank**, load `.local/lab-2/context.psql` in its own paste. Compare
the intended monitor's semantic and fused positions, then compare actual
contributions with the formula. Participants repair only `LAB2_EDIT` in
`labs/lab2_rank/rrf_contribution.sql`, apply, repeat and grade the saved request.
Read their actual ranks; do not demand a recorded example's exact positions.

In **2b — Re-rank**, distinguish reaching the shortlist from reaching the page.
`uv run python labs/lab2_rank/rerank_off_on.py` runs the request with reranking
off, then on; it shows a gain on size and resolution, not proof
of charging compatibility. The request filters Electronics and Monitor; its
size, resolution and power requirements are search text, not SQL predicates.

Run the judged-query comparison and ask which setting to test next and what
measurement is still needed. It measures candidate admission without calling
the reranker or changing served settings. Final relevance, latency and actual
cost remain separate measurements. Lab 2 ends with
`uv run python scripts/lab_state.py advance --lab 2`: it repeats Alex's request
and the two Dell requests that must still work, saves the passing evidence,
then installs the Retrieval agent's starting code. Retries prove Lab 2 again and keep
Lab 3 edits. Weighted RRF is optional.

### Lab 3: build, deploy and use the Retrieval agent

Discover Gateway tools, then complete `create_agent` inside `LAB3_EDIT` in
`labs/lab3_reason/agent.py`. Participants keep the supplied model, tools, source
rules and hooks, and add one instruction of their own. Deploy using the guide.

Use the deployment wait to predict the 100W answer. The resource tour is
optional. Seek room support after five minutes without completion, or two
minutes without new output; this is a support cue, not a deployment timeout.

After the deploy, participants ask Alex's setup request from the terminal with
`uv run python scripts/ask_agent.py "..."`, copied from the guide so it matches
the request completion checks word for word. It prints the answer, the plan, the
tool trace with the search SQL Aurora ran, the products, each citation with its
quote, the outcome and the **Run ID**. They ask the 100W follow-up the same way;
each call is its own run, and completion reads only the setup run's ID. A
follow-up question is not graded against the lab.

Ask Mosaic is optional. Its **Complete my setup** suggested question sends the same
request and passes completion only as the first message of a fresh chat (use
**Clear chat**); its **Builder view** shows the full run ID, recorded steps and
per-search ranks. The suggested question runs on its own filters and shows "Shop filters
were cleared for this lab request." when it replaces filters a participant had
set. After the request, Shop shows the terminal command that checks that run,
with its run ID filled in.
Inspect separate searches for the headphones, monitor and chair; all three in
the comparison and final shortlist; their supporting citations; and a ranking
explanation. Open the chair's listing and review: adjustable features and one
person's comfort experience make different claims. Check microphone evidence
separately from listening noise cancellation.

Ask the guide's changed 100W requirement against the monitor's 90W record.
The Retrieval agent must acknowledge the mismatch and any unknown compatibility.
Prove the **original setup run**, then finish the Conclusion checks. Completion
reuses the saved answer; a deployed endpoint alone is not a participant pass.

## Keep the architecture explanation short

Aurora owns products, vectors, eligibility filters, fusion, source evidence and
run records. Bedrock supplies embeddings, reranking and the answer model.
AgentCore Runtime hosts the Retrieval agent (built with Strands) and SQL tool service; AgentCore Gateway
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
Each search records the participant SQL Aurora ran it with, so `deploy_agentcore.py
verify` and `ask_agent.py` show that the Retrieval agent's searches through Gateway ran the
Lab 1 and Lab 2 files. The stack's `AgentObservability` parameter (default
`enabled`) traces Retrieval agent runs into CloudWatch's GenAI Observability pages; it never
decides whether Lab 3 runs, and `disabled` starts the runtimes untraced. When a
participant's question fails with HTTP 503 from the Retrieval agent, its runtime's
CloudWatch log names the cause, such as Bedrock throttling.

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

Before the event expires, use **Use it in your own agent** in Playground:
**Download the SQL and guide**, **Download the agent skill**, and **Connect over
MCP**. The skill guides a running backend; it does not host the
catalog or replace service permissions. Follow the
[adaptation guide](docs/use-in-your-app.md) for another domain.

Consult [READINESS.md](READINESS.md) for release evidence. Offline tests, live
development checks, a successful Studio build and a fresh-account rehearsal
prove different things. None substitutes for human timing or physical display checks.
