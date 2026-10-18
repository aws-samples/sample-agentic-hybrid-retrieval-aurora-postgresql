# Source and teaching audit, 18 October 2026

This is the initial audit snapshot. Subsequent local lesson and UI changes are
recorded in [the integration review](lesson-integration-2026-10-18.md); findings
below describe the source and guide revisions reviewed here.

Keep the three labs and their existing timing. The strongest improvement is to
spend less of the hour operating the workshop and more of it explaining three
decisions: which candidate was lost, why it survived the ranking cutoff, and
which claim the evidence supports. The source already provides substantial
L400 depth. The required reading and navigation sometimes conceal it, and some
opening explanations give away the investigation.

This audit reviewed application source `79fc9e773f0decf5272b8a5fe6f193174fa9a07f`
and the adjacent Workshop Studio guide at `72da75f`. That guide pins this source
revision. Review covered the participant entry points, three edit seams,
start/apply/deploy/proof paths, retrieval SQL, agent orchestration and evidence
checks, access boundaries, UI state and navigation, MCP packaging, CI gates,
curriculum documents and recorded rehearsal evidence. It combined source
inspection with offline execution. It did not perform a new Aurora, Bedrock,
browser, clean-account or human-timing rehearsal.

Only this audit document was added. Application code and guide content were not
changed. The guide repository's existing `BACKLOG.md` edit was preserved.

**Proposed participant flow**

| Existing slot | Keep on the required path | Cut, move or clarify |
|---|---|---|
| 0–10: introduction | Alex's request; candidates, ordering and supported claims; one architecture view | Avoid narrating the actual faults before investigation |
| 10–15: Getting started | Open Code Editor, establish the prepared connection, save the failing request | Move the column, vector, index and scoring tour to relevant deep dives |
| 15–25: Retrieve | Inspect membership, compare the three searches, reconnect the marked branch, apply, replay and hand off with controls | Show the repaired flow after diagnosis; keep Shop optional |
| 25–35: Rank and re-rank | Compare two unequal positions, repair the contribution, inspect candidate admission and reranking, read the judged comparison, prove | Make Shop entry self-contained; explain the difference between request text and enforced filters; put statistical detail behind the comparison |
| 35–55: Reason, including completion | Assemble and deploy early, inspect the original setup run, read a listing and review, challenge 90W against 100W, prove the original run | Replace the second-terminal resource tour with preparation for reading the evidence; avoid extra verification after a successful deploy unless something changed |
| 55–60: wrap-up | Explain one result and its limit, retain existing evidence, take questions | Remove required regrading and fresh agent requests from the closing slot |

These are proposed uses of the existing allocations, not measured completion
times. Keep the three files, marked edit regions, models, filters, settings,
source checks, negative controls and original-run completion requirement.

**1. Setup is carrying a second technical introduction. Delivery risk.**

The guide calls Getting started about five minutes, but it has ten numbered
steps. Before saving the failure, attendees inspect the catalog count, view and
table, a 44-column description, part of an embedding, indexes, function return
types and scoring examples. An approximate main-path inventory, excluding
expanders and image alt text, found 1,219 prose words, ten fenced command blocks
and twelve images. The two scoring tabs make this a content inventory, not a
measurement of what each person reads.

Evidence: Workshop Studio
[Getting started](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/15-getting-started/index.en.md),
lines 6–9, 49–202 and 245–275; source [START_HERE.md](../../START_HERE.md),
lines 3–8.

Keep opening the tools, one narrow readiness observation and the existing
`status` / `start --lab 1` sequence. Teach each column or operator beside the
decision that needs it. Retain the index and scoring material as optional
inspection. Do not make the first participant who needs clipboard help lose
their diagnosis time to a schema tour.

Suggested opening:

> Open Code Editor beside this guide. The application, catalog and Aurora
> connection are prepared. Save Alex's failing request now; Lab 1 uses that
> exact request to find where the intended product disappears.

**2. The opening reveals Lab 1's diagnosis before the observation. Teaching weakness.**

The first animation explains the missing `channels` branch and its repair;
the following code walkthrough identifies the gap before Task 1A's first
query. The lab README also states the missing search directly. This conflicts
with the intended prediction-first journey and reduces the exercise to copying
the answer participants have just seen.

Evidence: Workshop Studio
[Lab 1](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/20-lab-1-retrieve/index.en.md),
lines 20–38; [Lab 1 README](../../labs/lab1_retrieve/README.md), lines 8–23;
[AGENTS.md](../../AGENTS.md), participant journey instructions.

Start with the customer request, missing identity and one prediction. Keep the
generic three-search pipeline visible, then reveal the failure animation after
the independent-search query. The existing hints and solution remain available.

Suggested prediction:

> The request returned headphones but missed Alex's listing. Is the listing
> filtered out, missing from every search, or lost when the lists combine?
> Use the same request and filters to distinguish those explanations.

Keep the concluding question: why can reranking not recover this missing
candidate? That is a useful engineering lesson beyond the specific SQL patch.

**3. Lab 2 depends on an optional navigation step. Confirmed guide mismatch.**

Lab 1's Shop interaction is optional. Lab 2 opens by telling participants to
keep the Electronics tab and change the category currently labelled
Headphones. Someone who followed the required terminal path has neither state
and may be seeing Shop's first-visit tour.

Evidence: Workshop Studio
[Lab 1](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/20-lab-1-retrieve/index.en.md),
lines 197–215, and
[Lab 2](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/30-lab-2-rank/index.en.md),
lines 37–45.

Make the first Shop instruction complete from the landing page, including
opening Mosaic and choosing the category, or make the saved terminal failure
the starting observation and use Shop only for the ordering comparison. Prefer
an existing request/filter link if that can carry the intended state. Do not
require attendees to infer state left behind by an optional exercise.

**4. Make eligibility versus relevance the explicit Lab 2 decision. Teaching opportunity.**

The monitor request says 27 inches, 4K and 90W. Its structured filters contain
only domain and category. A 1440p result can therefore satisfy every enforced
filter while being a poor answer to the request. The guide discusses the bad
result and rerank limitations, but does not make this distinction prominent
enough at the first observation.

Evidence: `rank-with-evidence` in the
[mission manifest](../../data/evals/mosaic_labs_missions.json);
[filter implementation](../../db/sql/08_search_channels.sql), lines 23–51;
Workshop Studio
[Lab 2](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/30-lab-2-rank/index.en.md),
lines 211–221 and 242–250.

Suggested copy:

> Electronics and Monitor are enforced filters in this request. Size,
> resolution and charging power are words used to rank candidates. A 1440p
> monitor can pass those filters and still be a poor match. Read its listing
> before treating a high relevance score as proof that it meets the request.

Then ask which requirement a production application would promote to a typed,
validated predicate. This adds L400 judgment without adding another repair or
weakening the existing checks.

**5. The tuning comparison needs a narrower decision and honest terminal labels. Teaching and copy issue.**

The comparison measures candidate admission using cached search lists with
live identity and spot checks. It does not invoke the reranker or measure
latency. Increasing the cutoff over the same order cannot reduce the count
of admitted exact matches, so a longer shortlist winning that metric is not
by itself an interesting shipping decision. The important missing evidence is
final relevance, latency and the document lengths that affect billing.

The guide explains these limits, but the terminal calls its estimate a
“billed rerank unit per query” and asks what to ship. That wording can make the
same output look more conclusive than it is. A sign-test column also introduces
a new concept during a ten-minute slot without being necessary to the decision.

Evidence: [lab2_tuning.py](../../scripts/lab2_tuning.py), lines 46–63, 82–108,
180–234; [print_comparison](../../scripts/lab_exercise.py), lines 568–592;
Workshop Studio
[Lab 2](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/30-lab-2-rank/index.en.md),
lines 252–279.

Keep the judged-query comparison. Lead with admitted matches, queries better
and worse, and the known measurement limits. Label units as an estimate under
the one-document-per-listing assumption. Put the sign-test explanation in the
deep dive, and ask:

> Which setting would you test next? Name the candidate gain and one measurement
> you still need before shipping it.

Do not present the longer shortlist as a proven production improvement, or
change the served configuration to make this exercise look successful.

**6. Lab 3's depth is in evidence and control, not constructor syntax. Teaching opportunity.**

The participant maps supplied arguments into `Agent`. The supplied prompt
already specifies searches, comparison, evidence reads, ranking explanation
and final synthesis. The optional extra instruction is accepted when the
original instructions remain present; the assembly probe does not establish
that the addition improved behavior.

Evidence: [agent seam](../../labs/lab3_reason/agent.py), lines 12–24;
[supplied workflow](../../service/agent.py), lines 105–173;
[assembly probe](../../scripts/agent_assembly_probe.py), lines 12–41.

Keep the small assembly task because it connects participant code to Runtime.
Call out what was supplied and what they added. Make the payoff reading one
actual tool call and explaining one sentence against its source. During the
deployment wait, have attendees predict the 100W answer and identify which
claim a review cannot establish. The existing claim checker can support an
optional investigation; it does not need to become another required command.

Suggested outcome:

> Connect the supplied agent components, then trace one recommendation through
> your SQL to its source. Explain why a valid citation can still fail to support
> the customer's requirement.

The current guide correctly says that reading the sources and assessing the
100W follow-up are not automatically graded. Preserve that distinction rather
than describing the completion check as proof of those judgments.

**7. Progress messages do not provide a useful classroom escalation deadline. Delivery risk.**

The guide reports deployments taking one to four minutes and says to ask a
facilitator if nothing new appears for two minutes. The implementation can
continue reporting progress for up to 900 seconds per runtime, then wait up to
600 seconds for Gateway sync. Updates to the two runtimes are sequential. A
deployment can keep printing and still consume the entire lab.

Evidence: Workshop Studio
[Lab 3](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/40-lab-3-reason/index.en.md),
lines 89–106; [deployment polling](../../scripts/deploy_agentcore.py),
lines 282–319 and 388–440. The recorded October 4 deploys took 70.497 and
67.809 seconds, but those observations do not establish current tail latency.

Add a facilitator escalation point based on elapsed time without reaching
Ready, even if progress continues. Start deployment near the beginning of the
lab and use the wait for the evidence prediction. Treat the threshold as a
room-support cue, not a new timeout that kills a valid deployment or a reason
to accept an unverified run.

**8. Completion work has leaked into the closing five minutes. Confirmed guide mismatch.**

The session contract puts completion inside Lab 3. The wrap-up asks participants
to rerun the Lab 2 and Lab 3 exercise checks and says required work is done only
after both pass. It also asks for another agent request before leaving. These
steps compete with the promised Q&A time and reopen environment/model work
after the participant has already completed the labs.

Evidence: [presenter schedule](../../workshop.md), lines 15–28; Workshop Studio
[Wrap-up](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/50-wrap-up/index.en.md),
lines 44–60 and 80–87. [Lab 3's terminal message](../../scripts/lab_exercise.py),
lines 595–602, also tells a participant to change requirements after completion,
although the guide already asked them to do that before completion.

Remove the duplicate mandatory regrading when source, deployment and saved
runs have not changed. Locate the existing receipts, save them and discuss one
claim. Make the fresh free-form request explicitly optional. Align the terminal
Next message with that actual end state.

**9. The standalone MCP adapter rejects current search diagnostics. Confirmed source defect; release gate fails.**

The API now returns `RetrievalDiagnostics.search_sql_sha256`. The adapter's
independent wire model omits it and forbids extra fields. With diagnostics
enabled, a successful API search is therefore rejected when the adapter
validates the response. This affects the reusable MCP adapter, not by itself
the separate AgentCore Gateway tools runtime.

Evidence: [API model](../../service/models.py), lines 371–392;
[API population](../../service/retrieval.py), lines 640–656;
[adapter model](../../mcp-server/catalog_mcp/contracts.py), lines 44–47 and
202–215; [adapter validation](../../mcp-server/catalog_mcp/server.py),
lines 107–120.

Verification: `make mcp-install mcp-test` failed with 10 passed and 1 failed at
`contract_cases.py:338`, naming the missing field. An independent offline probe
serialized the application's diagnostics model and validated it with the
adapter model; it returned `extra_forbidden` at `search_sql_sha256`, even with
the optional field set to `None`. The wheel discovery smoke check passed, so
package installation/discovery alone does not catch this behavior.

Repair the wire model and exercise an API-shaped diagnostic response through
the adapter. Keep strict response validation. Do not hide the mismatch by
discarding unknown fields.

**10. Lab 3 completion checks today's deployment, not the saved run's SQL identity. Confirmed offline reproduction.**

The managed check compares the current Runtime application digest with the
workspace and the current applied SQL with the workspace SQL. It does not
compare the saved search's SQL digest with those values. The persisted mission
trace projection also omits the stored SQL hash. Entry checks establish that
the run followed lab start, not that it followed the current deployment.

Evidence: [managed completion check](../../service/lab_proof.py), lines 598–628;
[trace projection](../../service/lab_proof.py), lines 439–450;
[stored search digest](../../service/retrieval.py), lines 590–608;
[stored tool digest](../../service/agent_tools.py), lines 1975–1981.

Verification used the existing grounded fixture from `tests/test_lab_proof.py`,
the production `completion_proof`, and mocked Aurora/Gateway/Runtime boundaries.
The saved searches and search-tool outputs carried one SQL digest; current
Aurora and workspace carried a different digest, and current Runtime matched
the workspace. The proof returned `pass` with no failed checks. No live database
or AWS operation was used. This is an offline demonstration of the missing
comparison, not a claim about an observed participant deployment.

Bind completion to the application identity that produced the saved turn and
the SQL identities recorded for its required searches. Existing SQL digests
already provide part of the evidence. Preserve the rule that completion reads
the participant's original run without generating a replacement. Add a
regression case for run A, edit/apply/deploy B, then submit run A; include a
positive control for a run actually produced by B.

**11. Required-path documentation still describes retired work. Confirmed source/guide drift.**

Examples include the instructor schedule's evidence-attachment repair, a
curriculum requirement to inspect HNSW at two settings in Lab 1, a required
citation-tampering challenge, and a finale that runs three validators. Those
are not the current required journey. The guide's own AGENTS file still says
the required Lab 1 exercise grades a participant-written recall query, while
that query is now under Optional labs. These references can steer a presenter
or coding coach into extra work despite the correct current lab pages.

Evidence: [instructor guide](../../docs/instructor-guide.md), lines 48–53 and
340–343; [curriculum](../../docs/retrieval-curriculum.md), lines 54–62 and
145–159; Workshop Studio [AGENTS.md](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/AGENTS.md),
the paragraph beginning “Each lab has graded work”; its
[Optional labs](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/content/50-wrap-up/10-optional-labs/index.en.md),
lines 323–350.

Reconcile these documents to the current manifest and guide. Do not remove the
optional recall implementation merely because its old required-path references
are stale. Prefer one authoritative facilitator flow, with short links from
supporting documents instead of duplicate command sequences.

There is also a smaller mechanism mismatch in Getting started: its raw
`ts_rank_cd` query is described as scoring the way `search_fts` does, but the
production strict branch adds `1.0`, limits candidates and has a fallback path.
Label it an illustration of the underlying text-score function, or call the
production function. Evidence: Workshop Studio Getting started, lines 158–177;
[search_fts](../../db/sql/08_search_channels.sql), lines 129–163.

**12. One UI baseline test failed intermittently. Verification concern, not a confirmed participant defect.**

The first full UI run failed
`RetrievalLabPage > drops the stored baseline once the query stops describing it`:
`retrievalEventResponse` had been called once where no call was expected.
The isolated test passed, the entire test file passed, and a second full suite
passed all 915 tests. No source changed between these runs. Investigate
asynchronous cleanup and baseline restoration under suite load before calling
this gate reliably green; do not infer a visible baseline bug from these runs
alone.

Evidence: [test](../../ui/src/pages/RetrievalLabPage.test.tsx), lines 1061–1079;
[restore effect](../../ui/src/pages/RetrievalLabPage.tsx), lines 631–662.

**How to accommodate mixed experience without lowering the level**

Use the same requests, files and proofs for everyone. Make the existing supplied
repair easy to choose when syntax is the obstacle; retain the evidence question
for everyone. More experienced attendees can investigate an existing deep dive
while others finish, without becoming prerequisites for the room.

| Lab | Everyone explains | Optional depth already supported by the source |
|---|---|---|
| Retrieve | Where the intended identity disappeared, and which record proves it | The unread CTE in `EXPLAIN`; why a different typo can still be found semantically |
| Rank | Why unequal positions must contribute differently and why the cutoff matters | Integer division, sensitivity to `k`, judged-set coverage and latency evidence still needed |
| Reason | Which source supports one claim, and which changed requirement remains unsupported | Citation resolution versus claim support; retrieval scopes and application-owned checks |

For task B sections that inspect or compare, replace “Build / Nothing to edit”
with an action that names the actual work. The Workshop Studio
`scripts/guide_voice.py` validator currently fixes the repeated heading pattern,
so that editorial change must update its tests and the guide together. Preserve
navigation anchors or update their consumers deliberately.

Suggested framing for the whole session:

> You will repair three small connections in a prepared retrieval application.
> The work is to explain what changed: which products reach the shortlist, how
> they are ordered, and what the agent can support with their records.

**Verification record and remaining evidence**

| Check | Result |
|---|---|
| Source worktree before audit | Clean; lab status was Lab 1 SOLVED, Labs 2 and 3 NOT STARTED |
| Source/guide revision alignment | Guide's `SourceRevision` equals the audited source SHA |
| `make lint validate validate-db validate-config validate-release-workflow` | Passed, including bootstrap-copy agreement and 11 workflow tests |
| `mission_contract.py --shape-only` | 95 checks passed; live checks explicitly skipped |
| `env -u DATABASE_URL PYTHONPATH=. uv run pytest -q` | 2,391 passed, 41 skipped; teardown reported a pool worker that did not stop within five seconds |
| UI tests | First full run: 914 passed, 1 failed. Isolated test: passed. Full file: 53 passed. Second full run: 915 passed |
| UI production build | Passed TypeScript and Vite build |
| `npm audit --audit-level=moderate` | Zero vulnerabilities reported at audit time |
| `make mcp-install mcp-test` | Install/compatibility checks passed; tests: 10 passed, 1 failed |
| `make mcp-wheel-smoke` | Isolated installation and MCP discovery passed |
| API-to-adapter model probe | Current diagnostics rejected with `extra_forbidden` for `search_sql_sha256` |
| Saved-run identity probe | Different saved/current SQL hashes still produced a passing Lab 3 proof under mocked boundaries |

The recorded fresh-account work does not establish the current human timing.
[READINESS.md](../../READINESS.md), lines 175–180, and the guide's
[October 4 rehearsal](../../../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/release/rehearsal-2026-10-04.md)
explicitly leave human completion timing open. Before treating the tightened
path as fitting, observe attendees with different SQL/search/agent experience
using the actual guide. Record time to first useful result, time lost to
navigation, hint/recovery use, deployment wait and time to original-run proof.
Keep those observations separate from automated command durations.

The implementation work can stay small: repair the two evidence/adapter defects,
shorten setup and transitions, remove the duplicate closing work, then reconcile
the supporting documents. Preserve the judged-query exercise, real catalog,
source evidence, controlled repairs and negative controls. No fourth lab or
larger application rewrite is needed to make this session sharper.
