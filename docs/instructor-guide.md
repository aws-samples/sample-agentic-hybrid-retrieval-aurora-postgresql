# Instructor guide

## Pre-session checklist

Aurora only. There is no local database and no `make` target creates one. See
`ARTIFACTS.md`, including how to connect from a corporate network.

- confirm the base bootstrap with `make db-verify-bootstrap`, and the real
  catalog's 553,911 products and vectors through the restore's verification;
- save `build/bootstrap-timings.tsv`; report the measured `index_creation` and
  `total` rows rather than estimating them;
- run `MISSION_GATE_REQUIRE_DB=1 make validate-missions`;
- run `make validate-evals`;
- run `make validate-config`;
- run `FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions`;
- execute the eval harness and save a named baseline;
- run the HNSW matrix on the exact Aurora configuration used in the room;
- verify the three starter gaps, source revision, and Claude Code model from a
  fresh Workshop Studio deployment, and record that rehearsal with
  `scripts/checks/rehearsal.py` rather than loose command output — see
  [`docs/rehearsal-runbook.md`](rehearsal-runbook.md) for the full clean-account
  sequence and its evidence manifest; deployment, transfer, bootstrap, index,
  reranker, and agent timing belong in that manifest, not in this guide, so a
  stale number here can never disagree with what was actually measured;
- run `pytest -q tests/test_lab_state.py` so reset, solution, and isolation are
  byte-stable when repeated;
- run one configured-model rehearsal with
  `uv run python scripts/bench/benchmark_ask_mosaic.py --agent-model
  global.anthropic.claude-sonnet-5 --synthesis-model
  global.anthropic.claude-sonnet-5 --runs 1 --full-runs 1`; this warms the
  real retrieval, rerank, agent, and synthesis path;
- validate the expected room concurrency against the account's Bedrock quotas
  and the API pool with `scripts/bench/load_exercise.py` (see
  [`docs/rehearsal-runbook.md`](rehearsal-runbook.md#bounded-concurrency-exercise)),
  run once cold and once warm. Do not discover a quota limit from participant
  traffic, and do not print a latency or concurrency figure here that the
  exercise's own recorded report does not carry.

Rehearse against `reviews-2023-v2`. The prepared Aurora catalog has
553,911 imported records and vectors. Read `/api/readiness` and confirm both
API and terminal select that dataset. Live development checks do not prove
that the published Workshop Studio bootstrap loads this new dataset. Complete
the delivery-asset migration and fresh-environment rehearsal before the event.
The historical synthetic scorecard and 720 filter cases are not its quality gate.

## 60-minute path

| Clock | Stage | Required outcome |
|---|---|---|
| 00:00-00:15 | Introduction / Overview / Presentation | Meet Alex, frame the three lessons and explain the architecture |
| 00:15-00:25 | Retrieve | Restore one candidate channel and prove recall and eligibility |
| 00:25-00:35 | Rank | Repair RRF so the suitable monitor reaches reranking |
| 00:35-00:55 | Reason | Attach evidence identity to synthesis state, prove citation authorization and run the completion gate |
| 00:55-01:00 | Wrap-up and Q&A | Questions, then untimed optional exercises: Session & Memory first, with a retrieval tool or HNSW as alternatives |

## Eight proof anchors

Participants issue three before-and-after requests. Five additional anchors run
inside the production validators:

| Stage | Run | Proof |
|---|---|---|
| Retrieve | `G-003` | In this measured request, neither FTS nor the bounded semantic pool contains the target; restoring the trigram channel recovers it |
| Retrieve | `G-001` | Correct listing ID remains first with an exact-term match |
| Retrieve | `G-012` | Every saved product satisfies the Logitech brand and headphones category |
| Rank | `G-008` | RRF moves from rank-collapsing arithmetic to `1 / (k + source_rank)` |
| Rank | `G-007` | Dell U2720Q and SE2717H provide an explicit 4K-versus-1080p comparison |
| Rank | `G-009` | Dell brand and monitor category remain pre-ranking requirements |
| Reason | `G-021` | Evidence plumbing moves a fail-closed response to a grounded cited comparison |
| Reason | `G-019` | Logitech specification and sampled review claims resolve to separate source records; one review is one experience, and other reviews of the listing disagree |

The query text, filters, targets, bad observation, good observation, and
participant edit are owned by `data/evals/mosaic_labs_missions.json`. Workshop
Studio renders the three required requests, names all five controls, and checks
every rendered payload for drift.

## Teaching narrative

Use the opening, expert discussion cues, speaker roles, proof reading notes and
closing script in [Facilitation script](#facilitation-script) below; the presenter brief in
[`workshop.md`](../workshop.md) holds the clock and per-lab teaching points. The
participant guide's shape, graded work and
pacing are recorded in the [L400 lab design](l400-lab-design.md); the payloads,
repairs and validation sequence are unchanged by it.

### Repeatable delivery loop

For each lab, keep the canonical query, filters and runtime profile fixed. Ask
for a prediction, run the broken request, inspect the recorded mechanism, apply
the smallest repair, and run that identical request again. Record the request
and run ID in both states. A changed prompt or an unrelated result that looks
better cannot establish that the repair worked.

Use the [lab regression release sequence](lab-golden-queries.md) for
reset, apply, validation and recovery. `uv run python scripts/lab_state.py status` inspects source files;
it does not prove the running API or Aurora has loaded them. The validators
check the installed SQL and production responses. The browser's Lab 3 proof
does not run the separate evidence-grounding control; the terminal validator
remains the completion gate.

### Opening

"We have provided the catalog, embeddings and application scaffolding. You will
implement three critical connections and prove what changed. Retrieve asks
whether the right eligible candidates entered the pool. Rank asks whether that
pool was combined correctly. Reason asks which sources support the choice."

Point the room at the Playground before narrating any of it: `/labs/retrieval`
opens on **Hybrid retrieval**, the four-phase Retrieve, Rank, Re-rank and Reason
inspection, and each guide link adds `view=lab` to open that lab's exercise
with its rail: the three labs in order, each one's live repair state, and the
next lab to open. Say once that the labs, not the storefront or the Scale &
HNSW / Session & Memory tabs beside them, are the session, and move on.

Show the missed product first and collect a prediction. Leave the disconnected
path and its repair for Lab 1's diagnosis.

### Lab 1: Retrieve - Debug hybrid search

FTS is strong when words and identifiers exist. `pg_trgm` recovers nearby
strings. HNSW expands semantic intent. SQL predicates and JSONB filters decide
eligibility inside every candidate arm.

The request transposes two adjacent characters in a real listing ID. The
bounded meaning search returns plausible headphones without that listing.
Restoring `pg_trgm` admits Logitech Zone 900. Two other Zone 900 listings share the model
name but not the listing identity, so they are wrong too. Show both identifiers and
ask why other listings are wrong for an identity request; do not imply
that other headphones lack noise cancellation.

The exact-ID control proves FTS still works. G-012 uses a full-word Logitech need
with brand/category filters. Inspect both served rows and the complete saved
pool. An approximate vector scan can obey every SQL filter and still miss
qualifying rows; candidate count and eligibility are different checks.

### Lab 2: Rank and re-rank - Tune rank fusion and reranking

RRF combines independent rank positions without pretending raw FTS, trigram,
and vector scores share a scale. Cohere Rerank operates on the bounded fused
pool. It does not replace retrieval or override deterministic eligibility.

Ask attendees to compare per-arm rank, contribution, fused rank, and final rank
for the top two results. The line to land is: "A correct answer is not proof of
a correct pipeline." Historical weighted fusion is optional.

Before repair, the monitor request drops the ViewSonic VG2756-4K before
reranking. The collapsed formula ties every single-search candidate, so product
id decides the 50-product cutoff: the oldest listings stay, and a 1440p Lenovo
T27hv-20 appears among the final results for a 4K request. Inspect a source
position greater than 1: the broken formula gives it rank-1 credit. After
repair, the ViewSonic enters the combined list at position 21 and reaches final
position 5; read the participant's actual value.

Other feature requests retain their first result through the same faulty
formula. Use those as controls, not as visible repair demonstrations. The
[example library](real-catalog-exercise-library.md) includes successes,
unchanged results and an unsuccessful wording variant.

### Lab 3: Reason - Build and deploy the agent

Participants extend their SQL from Labs 1 and 2. They list the Gateway tools,
complete `create_agent` in `labs/lab3_reason/agent.py`, add one source-aware instruction,
and run `uv run python scripts/deploy_agentcore.py deploy`. The managed services and networking are prepared.

Show the deployment message, then ask **Complete my room** in Playground → Reason.
The agent searches for Alex's missing chair and brings it together with his Logitech
headphones and ViewSonic monitor. Open a citation and compare the recommendation
with its source. Follow up in Ask Mosaic with a 100W laptop-charging requirement; the
monitor's 90W record must not be presented as meeting 100W.

Participants build and use the agent. They do not write tests or a claims query.
The completion command `uv run python scripts/complete_agent.py --run-id ...` rechecks the actual run,
its deployed source and its SQL searches without another model invocation.


### Advanced Labs (OPTIONAL)

HNSW quality is workload-specific. The required path proves candidate inclusion and eligibility. The optional plan inspection reads the existing index. Recall/latency tuning remains optional rather than becoming a
rushed fourth lab.

After Lab 3, name the deployed boundaries: Aurora runs retrieval and stores
evidence; Strands chooses tools; AgentCore Runtime hosts the agent and SQL tool
service; Gateway exposes those tools over MCP; Memory supplies conversation
context. Product facts still come from Aurora.

## Facilitation script

These cues are for the people presenting. They add no required exercise and do
not change the mission contract. The manifest, `data/evals/mosaic_labs_missions.json`,
owns the requests, filters, targets and ranks quoted below; read participant
values from their own runs rather than from this guide. Keep the staffing roster
outside the repository.

### Spoken opening

> Alex works from home. He needs headphones for clearer calls, a chair for long
> days, and a monitor with room to run code and read docs. We have over half a
> million products in Aurora PostgreSQL. Can we find suitable options, put them
> in a defensible order, and explain a choice using the sources? You will repair
> one failure in each step and prove what changed.

> We have provided the catalog, embeddings and application scaffolding. You will
> implement three connections and use the recorded results to say whether each
> change worked.

Show the correct listing ID `B0C2WWCFQB` beside Alex's transposed request
`B0C2WWFCQB`, with the same headphones category and consumer electronics domain
filters. The correct ID retrieves the Logitech Zone 900 (product 1492978). With
Lab 1's fault installed, the transposed ID returns other headphones and omits
that listing. Ask where it was lost before opening the search details. Do not
say the other headphones lack noise cancellation; the visible error is
identity, not features.

The opening has seven beats in ten minutes. They are speaking cues, not seven
participant tasks. Keep slides to the question each lab answers, and keep SQL,
plans and measured comparisons beside the lab that uses them.

| Clock | Beat | Say and show | Owner |
|---|---|---|---|
| 00:00-01:00 | Meet Alex | Show the home-office brief. Ask what would make a recommendation worth following. | Lead |
| 01:00-02:30 | A search that misses | Run the correct and transposed listing-ID requests with identical filters. Save the broken search. | Lead |
| 02:30-04:00 | Retrieve | Show the three search methods and ask which record would locate the missing product. A reranker cannot add a product it never receives. | Technical |
| 04:00-05:30 | Rank | Ask how we know fusion worked if a monitor finishes well. Participants will restore `1 / (k + rank)` and defend a setting on judged queries. | Technical |
| 05:30-07:00 | Reason | Preview the final request below. Do not start a long agent run in the opening. | Lead |
| 07:00-08:30 | Who owns each decision | Aurora retrieves, filters and saves records. Bedrock supplies embeddings, reranking and the agent model. The application validates tool calls and citations. Show one saved search ID. | Aurora presenter |
| 08:30-10:00 | Your work and its proof | Open the guide and both work surfaces. Predict, observe, diagnose, repair, repeat the same request, explain the change. Required work finishes by minute 50. | Lead |

Lab 3's request, from the manifest:

> I have the Logitech Zone 900 headphones and the ViewSonic VG2756-4K monitor.
> Now I need a chair, and I'm looking at the Steelcase Gesture. Help me complete
> my room, and show me the sources for all three.

Lab 2's request is `27 inch 4K monitor USB-C 90W laptop charging` under the
consumer electronics domain and monitor category. Its target, ViewSonic
VG2756-4K (product 1551237), is absent from the combined 50 before the repair.
After it, the target has meaning rank 10, combined position 21 and final
position 5. A Lenovo T27hv-20, which is 1440p, appears among the broken
results for a 4K request. Do not require the target to lead before reranking and
do not label every other monitor unsuitable.

### Expert discussions inside the proof time

Ask these while participants inspect records they already have. Start with the
participant's prediction and finish with the observed result.

| Lab | Ask | Read together | Limit the conclusion |
|---|---|---|---|
| Lab 1: Retrieve - Debug hybrid search | The filters are correct. Why might vector search still return too few eligible products? | Applied filters, returned counts and, if recorded, the plan with scan settings, rows and buffers | Eligibility does not establish coverage. HNSW can visit rows that fail a filter, and iterative scanning explores further within its limits. An opaque function scan does not reveal its index. |
| Lab 2: Rank and re-rank - Tune rank fusion and reranking | The final winner looks right. What proves fusion worked, and what justifies the reranker? | Different source ranks, their contributions, combined and final positions, and the judged-query comparison | A correct winner cannot certify the formula. Count improvements and regressions on the judged queries; repairing RRF saves no model call. |
| Lab 3: Reason - Build and deploy the agent | The citation opens. Which words support this particular requirement? | One claim, its source type and revision, the product and its saved search | A specification and a review answer different questions. Registering evidence permits a citation; it does not establish that a sentence follows from it. Say what remains unknown. |

In Lab 3, also point to the separate searches for the headphones, monitor and
chair, and identify which calls the model requested and which the application
started. Playground's **Steps and sources** reports these separately and shows
**Origin not recorded** for steps that lack the field. Tool activity records
actions; it is not a transcript of model reasoning. If time is tight, use the
existing runs and ask one question per lab. Do not launch another agent run or
open the HNSW exercise to fill a speaking cue.

### Reading the proof

Playground follows Retrieve, Rank, Re-rank and Reason down the page. Read one
selected search across Retrieve and Rank, then follow a recommendation's search
link from Reason. A multi-part question can call Retrieve and Rank several
times, so the sections describe responsibilities, not one execution order.

1. **Retrieve:** inspect filters, counts and how each preview product was found.
2. **Rank:** follow the same products before and after reranking and open the
   contribution calculation to see why positions changed.
3. **Reason:** read the answer, compare its sources and follow a pick back to
   its saved search. The activity log separates model-requested calls from
   application-started ones.
4. **Prove within each lab:** the lab view holds the repair checks. They answer
   a different question from the saved measurements, which describe quality
   across a judged query set and do not grade a participant.

**View retrieval event** reads saved ranks and the original environment; its
eligibility check uses the current catalog. **Run EXPLAIN ANALYZE** executes the
SQL again with the saved query, filters and settings, so it reads current
functions and data and replaces the saved plan without changing the original
ranks. Read estimated and actual rows, loops, planning and execution time,
buffers and settings. Buffer counts at a parent node include child work. SQL
inside a `plpgsql` function can appear as one opaque Function Scan, and the
summary lists only index names visible in the plan.

Check what a measurement means, not just its number and unit. Battery life does
not establish recommended daily use, and Mosaic rejects that substitution even
when the citation resolves to the right product. Keep three questions apart:
did anything we depend on stop working, how good is ranking across the judged
set, and did a hard filter ever leak.

For the chair, adjustable features and one person's comfort experience are
different claims. For the headphones, check microphone evidence separately from
listening noise cancellation. For the monitor, the changed 100W requirement must
be checked against the 90W record, and unknown laptop compatibility stays
unknown.

### Speaker roles

Assign people outside the repository. These are responsibilities, not extra
talk slots; one person can cover several roles.

| Role | Owns | Handoff or review question |
|---|---|---|
| Lead presenter | Customer story, clock, projected browser and transitions | What changed for Alex, and which record shows it? |
| SQL presenter | Candidate paths, filtering, fusion arithmetic and plan reading | Does the SQL or plan support the database claim? |
| Agent presenter | Tool decisions, application checks, source comparison and claim support | Which action did the model request, and what could the application refuse? |
| Room support | Navigation, syntax recovery, validator results and Hint 4 pacing | Can the participant explain the repair using their own result? |
| Technical reviewer | Challenging database, ranking and answer claims during rehearsal | Does the plan support the claim, does the measurement justify the setting, does the source support the answer? |

The lead keeps asking what the shopper saw, why seeing a product is not enough
to call retrieval healthy, and which of the three lab questions the proof
answers. The technical presenter keeps asking which search method contributed
and which stayed silent, where the product sat before reranking, and whether the
application registered the evidence or only the model saw it. Room support gets
participants to the proof without weakening a rule, creating a local database
or treating a facilitator's screen as their evidence.

### Closing script

Lab 1 taught us that a healthy component can sit inside a broken pipeline, and
that recall comes before ranking.

Lab 2 taught us that a correct answer is not proof of a correct pipeline, so
ranking has to stay inspectable. Its exercise check requires the repaired
contribution function and saved fusion scores that agree with it, with the
target present. A saved run from before the repair must be repeated first.

Lab 3 taught us that the application controls which evidence may be cited and
that the cited text must still support the particular claim. A USB-C port alone
establishes neither laptop compatibility nor charging power; those need explicit
support in the cited record.

The method:

> Find the search method that stayed silent, repair the smallest seam, run the
> same request again, and prove it from what Aurora recorded.

After the completion check, run **Bring Alex's office home** in the guide's
Conclusion. It reads the participant's own saved runs. Ask one participant for a
claim, another for its source, and another for what Alex still needs to check.
Use the existing runs; do not start a new model call to produce a cleaner finale.
The completion check rechecks the participant's saved run; the scorecard is a
separately dated measurement.

Close with **Take this retrieval into your own agent** in Playground: **Connect
retrieval tools**, **Download the skill**, **Adapt the implementation**. MCP or
HTTP connects another host to a running service; the skill adds workflow and
evidence-checking guidance for those tools. Neither enforces permissions; the
service and database role do. The skill does not host the catalog, and the event
backend expires with the workshop. Then introduce the optional Memory exercise:
Memory answers what we remember about Alex, not which product fact is true.

## Failure-safe sequence

1. If the environment is delayed, inspect the asset download, cache verification,
   catalog load, and index-build timings before changing the bootstrap contract.
2. If cache access, KMS access, Aurora connectivity, or a required Bedrock
   model is unavailable, stop the affected exercise and escalate the environment
   issue. Do not switch to fixtures or a local database.
3. Catalog inspection remains available when model access is unavailable, but
   model-dependent retrieval must report failure rather than fabricate results.
4. To show an expected state during an outage, replay it from the instructor's
   own rehearsal output. Nothing the instructor shows counts as evidence that
   a participant check passed. Incident and fallback screenshots are retired
   workshop assets; do not reintroduce them.
5. If `psql` hangs while the port is reachable, inspect TLS settings before the
   security group. See `ARTIFACTS.md`.

## Suggested audience questions

- Which query failures require lexical, fuzzy, or semantic retrieval?
- Which constraints must never be delegated to a reranker?
- Why did result 1 outrank result 2 before and after reranking?
- What evidence should an agent retain for a recommendation?
- How much Recall@K would you trade for p95 latency in this workload?

## Carry the story and reuse the proof

Alex's need for more screen space has its own band on the Shop landing, matching the presentation and Shop's monitor example. Lab 3 brings the headphone, monitor and chair decisions together: carry forward the monitor requirements from Lab 2 and gather separate evidence for each item. The monitor is also an exact-model control and an optional HNSW example. The SQL repairs feed the deployed agent; the mission and evidence checks cover the monitor's size, resolution, USB-C video and charging.

Ask each checkpoint question before the SQL repair. In Lab 3, show the monitor
and chair searches and open one source. Distinguish a deployment failure from a
working answer that declines an unsupported claim.

At completion, use the participant's run ID:

```sh
uv run python scripts/complete_agent.py --run-id <run-id>
```

The receipt binds the deployed code and current settings. It is regraded from
Aurora; a facilitator demonstration does not complete a participant's exercise.

Offer Session & Memory first in the five-minute wrap-up; extraction is asynchronous, so do not promise a completed extraction in that time. [Build a retrieval tool](build-retrieval-tool.md) is the alternative: its four hints preserve the final two-budget proof and agent call. HNSW is the other option. Use [the delivery map](abstract-delivery-map.md) to distinguish what attendees implement from what they inspect.
