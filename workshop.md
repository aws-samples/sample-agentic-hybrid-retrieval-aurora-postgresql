# DAT410 Mosaic — Co-Presenter Brief

> Staff brief, written in plain language. It carries no secrets, so it is fine for a participant to find it in Code Editor. Use it to understand the story, divide presenter roles, and answer questions the same way at every table. The operational checklist lives in the Workshop Studio repository's `FACILITATOR_GUIDE.md`; this file does not repeat it.

## The workshop in one minute

Participants are the engineers; Alex is their customer. Alex is setting up a home office for coding, video calls and focused work.

- **A reranker cannot recover a product that never entered the candidate pool.**
- **A correct-looking result can hide broken ranking.**
- **Returned evidence still has to be registered before it can support an answer.**


Mosaic is a shopping catalog of 500,000 products across consumer electronics, running and fitness, and home office. A shopper can search with keywords or ask in plain language. Both paths run against one Aurora PostgreSQL database, and both can look right while the retrieval behind them is wrong.

Participants repair three deliberate faults in that pipeline, one per lab, and prove each repair from evidence the database records:

1. **Retrieve — find the options.** Which eligible products can we find?
2. **Rank — establish their order.** How should we order those products?
3. **Reason — support a decision.** What choice can the sources support?

The engineering proof follows the customer question: candidate membership,
rank contributions, then claims tied to product evidence. **Prove belongs in
all three labs. It is not a fourth stage.**

Every lab uses the same rhythm: **Broken, Diagnose, Fix, Prove.** The fix is small on purpose. The point is the diagnosis and the proof.

The central lesson is:

> Retrieval correctness is a pipeline property, not a top-1 result.

A plausible product card is not proof that search is healthy. A correct final answer is not proof that ranking was correct. Evidence the model has seen is not citable until the application says so.

### The spoken opening

> Alex works from home. He needs headphones for focus, a chair for long days,
> and a keyboard that stays quiet during calls. We have half a million products
> in Aurora PostgreSQL. Can we find suitable options, put them in a defensible
> order, and explain a choice using the sources? You will repair one failure
> in each step and prove what changed.

Show three brief searches under Electronics, in-stock and under-$200 filters:
`something to help me concentrate when the house is loud`, then the correctly
spelled control `noise cancelling headphones`. Finally show
`noice cancelng hedfones`: the Sonora WH-C720 disappears. Search is not completely
broken; one candidate path is disconnected. A healthy close-spelling index can
find the target, but its rows never reach fusion. Only the current lab's fault
is installed.

Use each product's search details as well as aggregate counts: the meaning-only and broken
typo requests can both show only semantic candidates while answering different
questions. A correctly spelled request can also receive close-spelling matches.
Pin the broken typo receipt before repair and repeat the identical request after
repair; the baseline survives the required reload.

Lab 2's current fixture swaps the fused top two while keeping the final winner.
The essential diagnosis is equal contributions for unequal source ranks. Even
if a different run already shows the expected winner, inspect and repair that
formula; a plausible first result alone cannot pass the production validator.

Lab 3 separates authorization, relevance and claim support. Registered evidence
IDs authorize citation; a separate review checks the current request and its
requirements before answer writing. Unknown device compatibility and unrelated
follow-ups decline without product cards. This review adds one bounded model
call to a supported answer and records its usage; it does not turn semantic
judgment into a deterministic guarantee.

## Introduction / Overview / Presentation

Reserve the first **10–12 minutes for the presentation**, regardless of how
quickly participants can open their accounts. The planned agenda allocates 12.
Do not turn this block into troubleshooting or an early start on Lab 1.

### The opening: seven beats in twelve minutes

Show a customer problem before explaining its machinery. One lead carries
Alex's story; technical and Aurora presenters explain the records behind it.
Table facilitators use the same three stage questions. These are speaking cues,
not seven additional participant tasks.

| Clock | Beat | Say and show | Owner |
|---|---|---|---|
| 00:00–01:00 | Meet Alex | Show the home-office brief. Alex needs focus, comfort and quiet typing. Ask: what would make a recommendation worth following? | Lead |
| 01:00–03:00 | A search that misses | Show the headphone control and the misspelled request with identical filters. The target disappears even though Shop still returns products. Save the broken search. | Lead |
| 03:00–04:30 | Retrieve: find the options | Show the three search methods and the missing product's path. Filters decide eligibility; a reranker cannot add a product it never receives. | Technical |
| 04:30–06:00 | Rank: establish their order | Preview the question, not the next fault: if a chair finishes first, how do we know fusion worked? Participants will inspect source ranks and `1 / (k + rank)` before reranking. | Technical |
| 06:00–08:00 | Reason: support a decision | Preview Alex's final request: a quiet mechanical keyboard and a chair for 12-hour days, each under $800. One request needs separate searches and source comparisons. A source link must support the claim. Do not start a long agent run during the opening. | Lead |
| 08:00–10:00 | Who owns each decision? | Aurora retrieves, filters and saves records. Bedrock supplies embeddings, reranking and the agent model. The application validates tool calls and citations. Read-only catalog tools still produce audit writes. Show one saved search ID, not a service tour. | Aurora presenter |
| 10:00–12:00 | Your work and its proof | Open the guide and the two work surfaces. Observe, diagnose, repair, repeat the same request, explain the change. Only the current fault is installed. Fast track keeps the same proof. Required work finishes by minute 52. | Lead |

The slides introduce a question; each lab answers it with real records. Keep
SQL, plans, budgets and measured comparisons beside the relevant proof instead
of front-loading them into the opening.

### Where the technical depth belongs

| Idea | Show it here | Check, rather than claim |
|---|---|---|
| Candidate coverage and filters | Lab 1; Retrieve's search details | The target entered through close spelling and the ineligible control stayed out |
| Filtered vector search | Lab 1's expanded plan; optional Scale & HNSW | `ef_search` controls HNSW search breadth; filtering can leave too few matches. Iterative scans can explore further within their limits. It is not a universal returned-row cap. See the [pgvector filtering documentation](https://github.com/pgvector/pgvector#filtering). |
| Rank fusion and model reranking | Lab 2; Rank | Unequal source positions produce different contributions; a plausible final winner does not prove the formula |
| Agent choices and application rules | Lab 3; Reason's activity and sources | The model chooses focused searches and asks for tools. Validated arguments, preserved filters and scope checks constrain execution; a typed interface alone does not guarantee correctness |
| Citation and claim support | Lab 3; source records | Registration makes an evidence ID available for citation. The cited record must also support the particular claim |
| Persistence, time and cost | Saved search, plan and agent records | Catalog reads create audit writes. Read measured latency and usage; do not imply one transaction spans the model-and-database workflow |
| Method comparisons | Retrieve's **Compare search methods**; guided **Prove** | Compare all five measured methods on the same graded searches, including cases that get worse |
| HNSW tuning, tool extension, AgentCore Memory | Optional work after completion | Memory can retain preferences; fresh catalog evidence still supports product claims |

Discover introduces the person and the problem; Shop supplies the choices. The
photographed workspace selection keeps the first impression focused on Alex.
Search still reaches 500,000 products. The scale reveal belongs beside search
and in Playground.

## Alex’s journey

**Discover opens with “A room built around the way you work.”** A large photograph shows the
workspace Alex is working toward. Beside it, **Meet Alex** makes the brief
specific: a software engineer whose day moves between coding, team calls and
focused work. His desk and laptop are already in place. His headphones, chair
and keyboard are still to choose. The portrait and brief establish the customer;
there is no shopper login exercise or invented “2 of 7” completion counter.

The slide-ready [Meet Alex bio and full-resolution headshot](docs/presentation-assets/meet-alex.md)
use the same persona.

The next section is **Three needs. One working day.** Each illustrated story
explains the situation, names the details that matter, and offers a pill that
runs a real, category-scoped Shop search. The order matches Shop’s Explore pills:

| Alex’s need | The customer problem | What the choice must establish | Where the story goes |
|---|---|---|---|
| **Clearer calls** | Background noise at home makes it harder for teammates to hear him. | Microphone clarity for the person listening, plus comfort and noise cancellation for Alex. Listening noise cancellation alone does not establish outgoing voice clarity. | Find headphones for Alex → headphones search and comparison. |
| **Comfortable days** | A short call becomes a long coding session. | Lumbar support, seat depth and arm adjustments that fit his body and working day. | Find chairs for Alex → chair search and comparison. |
| **Quiet typing** | Alex takes notes while teammates talk. | Typing noise, mechanical feel, layout and wireless connection. | Find keyboards for Alex → keyboard search; **Plan my workspace** searches both keyboard and chair needs. |

From there, the customer experience continues:

1. **Shop the choices.** Browse the workspace edit or search the full catalog.
   Discover’s story actions and Shop’s matching Explore pills use the same
   queries and filters from the mission manifest. A visitor can also describe a
   different need in the general search box.
2. **Look closely.** Open a product for its complete description, specifications
   and reviews. Similar monitors are alternatives; monitor arms, docks and cable
   management are supporting categories whose compatibility still needs checking.
3. **Ask for help choosing.** Ask Mosaic gathers and compares evidence, then
   explains its shortlist with product images and citations. Follow-ups can use
   the previous grounded run in that conversation.
4. **Continue the workspace.** On the first unfiltered Shop page, a separate
   supporting edit offers lighting, a dock and a laptop stand. Its products and
   prices come from the catalog. It disappears during search, filtered browsing
   and Ask Mosaic, keeping the retrieved result set clear.
5. **Inspect the system behind the choice.** Participants move to Playground to
   see which products entered the pool, how their ranks changed, and what evidence
   supports the answer. Scale & HNSW explains the search across 500,000 products.

Discover establishes the brief and carries no product inventory grid or lab
instructions. The guides remain the participant entry point and install each
lab’s deliberate fault. The customer journey above gives those repairs context;
the core lab contracts and the transition into Reason are specified below.
Cross-conversation preference memory is an optional extension, not something the
Welcome Alex profile or the Discover brief already implements.

## What participants do

1. Open three browser tabs from the Event Dashboard: Code Editor and Mosaic, plus the guide itself.
2. In Shop, observe the correctly spelled control, then search `noice cancelng hedfones` and see the Sonora WH-C720 missing. That contrast diagnoses the starting fault.
3. Lab 1: reconnect the close-spelling search arm to fusion, in SQL.
4. Lab 2: repair the fusion arithmetic so rank position counts again, in SQL.
5. Lab 3: register retrieved evidence into the application state that authorizes citations, in Python.
6. Run the completion gate inside Lab 3, then use the remaining time for an optional exercise, catch-up or questions.

Each lab has a manual path and an optional coding-agent path (`claude` from the repository root, with guardrails). Both produce the same small diff and pass the same validator. Each lab also has a five-minute **Fast track** that compresses the implementation, never the proof.

## The participant experience

### Code Editor

A browser VS Code with a terminal already connected to the participant's own Aurora cluster, so `psql` needs no connection string. Participants edit two files across the three labs:

- `db/sql/09_search_functions.sql` for Labs 1 and 2;
- `service/agent_tools.py` for Lab 3.

`uv run python scripts/lab_state.py status` reports each lab as BROKEN or SOLVED. At the start, Lab 1 is BROKEN and Labs 2 and 3 read SOLVED; each later lab resets only its own fault and keeps the repairs already made.

The guided Playground uses **Code needs repair** or **Code repaired** for the file and
**SQL repair not applied** or **SQL repair applied** for Aurora. Lab 3 says
**No SQL update required**. These describe the repair's installation; only the
completion proof verifies its behavior. The storefront header carries navigation,
and the Playground lab rail carries these exercise states.

### Mosaic

The application has three navigation destinations, with Ask Mosaic inside Shop:

- **Discover.** The home-office brief described above: Alex, his room, three needs, and routes into search or category browsing. The illustrated scenes are inspiration, not a product bundle or a completed purchase.
- **Shop.** The default Workspace edit currently shows 71 picks selected from the 200 photographed products; keyword search reaches the full 500,000-product catalog. Every result card can open "See how this was retrieved", carrying the query, filters and saved search event into the Playground. Ticking two or more results compares them side by side, and the comparison is worth showing: under the price and the rating it prints which search methods found each product, its rank before reranking, and the rank the shopper was shown. Those three rows come from the run's saved receipt, not from the list on screen, which is why a comparison is only offered once a search has run. If the catalog carries none of a request's words, Shop says which ones above the results rather than returning a confident page of near misses.
- **Ask Mosaic.** The agent, in a side panel on Shop or a mobile overlay below the header. The catalog retains its margins at normal laptop zoom, and long questions wrap in full. The panel keeps its title and follow-up box visible, with compact waiting and completed steps. It shows progress while gathering evidence, then leads with the cited answer. **Steps and sources** holds the request interpretation, searches, product comparison, supporting evidence, and tool activity. Follow-ups carry context from the prior grounded run with memory off. **Use saved memories** is a separate, optional control using the Playground's AgentCore Memory connection. **Memories used** shows actual records read and conversation-save status. Clearing chat starts a new conversation and keeps saved preferences. Required lab requests keep memory off. A specs-and-reviews question explains the available specifications and missing review excerpts without implying the product is absent or inventing customer experiences.
- **Playground.** `/labs/retrieval` defaults to **Hybrid retrieval**, a three-stage inspection of Retrieve, Rank and Reason. Each column ends with a **Keep in mind** line that states the lesson the column proves, and Retrieve's search details add one more beside the search record, on the receipt and the HNSW settings; the stage questions are the ones introduced in the opening. Alex's request choices come from the canonical mission manifest. One send action, the same paper plane Discover uses (its tooltip reads **Run Mosaic**), makes a real agent request; the stages read its records. A saved Shop event opens its original receipt, and Run Mosaic starts a new complete run when an agent answer is needed. **Scale & HNSW** is the adjacent inspection lens.

Hybrid retrieval also offers **Plan my workspace**, which resolves its question and
filters from Lab 3, and **Check the sources**, which compares a specification
with sample review evidence. Source comparison stays inside Reason and includes
records the agent read but did not cite. Missing review evidence is shown as
missing, not filled in.

The Workshop Studio guide contains **Build a retrieval tool**, a starter-generation
exercise and a live API check with two budgets. Coding instructions live in the guide,
not on a Mosaic app page. Its downloadable guide maps the schema, ranking SQL,
model integration and evidence boundary for adaptation after the session. Use
this extension during flex time or as take-home work; it adds no required lab.

The guides and proof links retain the three stages and an unnumbered **Prove** section through
`example`, `run`, or `view=lab` on `/labs/retrieval`. Use those guide links for
the exercises below. The home-office presentation does not change any core lab
question, target, repair or completion contract. The installed Shop selection has 200 individually written, concise descriptions.
Its source, Aurora rows, Cohere vectors and specification evidence are promoted
together. `data/curated/proposals/` retains earlier design sketches; the active
source is `data/curated/demo_products.json`.

Product pages carry the same typography and shopping controls. “Similar monitors”
uses the stored product vector to find alternatives within the photographed
selection. “Complete your setup” points to monitor arms, docks and cable
management separately; those category relationships do not assert that every
accessory fits. VESA patterns, display weight, desk clamp range and connection
requirements are the facts needed to establish compatibility. A whole model or
SKU lookup serves the matching identity without padding the result with weak
neighbors; Playground retains the complete candidate audit.

Shop introduces Alex beside a compact title, then shows three large scenes:
headphones for focus, a chair for comfort, and the complete workspace. Their
Retrieve → Rank → Reason labels follow the core mission order; the captions
tell the shopping story without giving exercise instructions. Search and Ask
sit immediately below. The scenes scroll horizontally on mobile and step
aside during a search or an open Ask conversation.

Explore and Ask follow the canonical Hybrid retrieval request order: **Clearer calls**,
**Comfortable days**, **Quiet typing**, then the **Mosaic Atelier 32** exact-model
control.

Hybrid retrieval opens on Clearer calls. Comfortable days adds a scoped
chair-shopping request; it does not change Lab 2's question or proof. Ask shows
only suggestions compatible with the current filters.

### The guided Playground, stage by stage

- **01 Retrieve.** Three ways Aurora looked for the same product: exact terms (full-text search), close spelling (trigram matching), and meaning match (vector similarity). Each shows how many candidates it put in the pool. In the broken Lab 1 state the close-spelling arm reads "not in this pool" while its index is healthy. That contrast is the whole lesson.
- **02 Rank.** One table, one row per result: where each product sat in each arm, its fused position before reranking, its rerank score, and its final position. Select a column heading to read the SQL behind it.
- **Repair evidence.** Paste two persisted run ids to see what a fix changed.
- **03 Reason.** Run the agent on the mission question. Focus moves to one results area, with the current stage, elapsed time, and recorded counts above a vertical sequence of progress and results. The evidence chain traces products retrieved, evidence returned to the model, evidence registered, evidence authorized, citations resolved, and grounded answer. In the broken Lab 3 state the run refuses to answer, and that refusal is correct. An interrupted run retains the available receipts for diagnosis.
- **Prove, in every lab.** The participant’s current repair checks, followed by the maintainers’ scorecard, in five plain sections: can search find the right products, did known-good checks still pass, did hard filters hold, did the agent stay inside its evidence rules, and what each ranking step added. Then the package finale: the SQL, the eval harness and the citation guard to take home, with the skill that describes how an agent calls them.

Every number on the Playground is a value the run reported. Nothing is typed in, estimated, or animated for effect.

The completion proof evaluates the mission, not just a successful response.
Retrieve and Rank also run their independent supporting controls. Reason checks
the persisted question, target searches, tool activity, evidence, citations, and
retrieval explanation. Starting another run clears the previous proof; a prior
PASS cannot certify a pending or failed attempt.

## The three-lab journey

| Lab | What Alex sees before | What is broken | PostgreSQL and model mechanisms | Small repair and good state | What proves it |
|---|---|---|---|---|---|
| **Retrieve — 10 min** | Correct spelling works; the misspelled headphone search loses Sonora WH-C720. | The trigram search works on its own but its rows never enter fusion. | `tsvector` / `tsquery` with GIN for terms; `pg_trgm` for close spelling; pgvector and HNSW for meaning; SQL eligibility filters inside each arm. | Reconnect the `typo` CTE and union. The same typo now returns the eligible headphones. | Product 2 has a real trigram contribution in the saved run; Lab 1 validator passes. |
| **Rank — 10 min** | The final first chair looks correct, while the wrong chair leads before reranking. | Reciprocal rank fusion assigns every source rank the same contribution. | SQL combines ranked candidate sets using **RRF**, `1 / (k + rank)`. **Cohere Rerank** on Bedrock reorders the bounded pool. Raw scores from different arms are not directly comparable. | Restore the contribution formula. PostureWorks Pro Mesh leads before and after reranking. | Inspect per-arm contributions and pre-rerank movement; product 370002 leads; Lab 2 validator passes. |
| **Reason — 20 min** | Ask Mosaic finds products and reads their specs but refuses to produce a cited recommendation. | Evidence reaches the model but is not registered in the application state used to authorize citations. | A Strands agent calls typed tools; Aurora supplies products, saved search receipts, `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)` and versioned evidence rows. The application validates citation IDs and ownership. | Repair the one registration block in `get_product_evidence`. Product images, a comparison and a grounded answer appear. | Independent target searches, comparison, evidence reads, a saved plan and resolvable citations; Lab 3 and the completion gate pass. |

**Retrieve:** a reranker cannot recover a product that never entered the pool.
**Rank:** a correct-looking result can hide broken ranking. Cohere is masking a
math bug, and a model call has cost and latency. Repairing fusion does not itself
remove the reranker call; claim savings only when a separate measured policy
actually skips it. **Reason:** returned evidence must be registered before it
can support an answer.

**Filters deserve their own explanation.** Each SQL arm applies eligibility
before its candidate limit. Eligibility and the limit are two budgets, and
neither gets to change the other. That does not mean an HNSW graph only visits eligible
rows: selective filters can leave an approximate scan short, and iterative scans
may need to explore further. Inspect both eligibility and candidate count.

### The handoffs: one customer, increasingly demanding questions

| Transition | Spoken bridge | What carries forward |
|---|---|---|
| Retrieve → Rank | “We can now find the missing headphone. Alex next needs a chair. Finding suitable products is the start; now show that their order has a sound basis.” | The repaired retrieval path and its eligibility checks, not a headphone selection or a shared result list |
| Rank → Reason | “We have a chair shortlist for long workdays. Alex now specifies 12-hour use and dynamic lumbar support, and adds a quiet mechanical keyboard. Does the earlier choice still fit?” | The repaired search and ranking, with fresh searches for the refined request |
| Reason → decision | “Choose one recommendation. Show which source supports it, why an alternative falls short, and which search brought it into consideration.” | An answer the customer can inspect, backed by the records participants just repaired |

**Make the changed requirement explicit.** Lab 2's PostureWorks chair (`370002`)
lists 10-hour use and adjustable lumbar support. Lab 3's Mosaic Forma chair
(`370001`) lists 12-hour use and dynamic support. That is a reason to reconsider
the earlier shortlist. Lab 3 does not automatically consume a saved Lab 2
selection, and the required path uses no cross-session memory.

The keyboard comparison is equally concrete: quiet does not by itself mean
mechanical. Inspect the switch type and noise evidence behind the options the
run actually returned. A cheaper option may meet the requirements too; explain
a supported tradeoff or say the sources do not establish a reason to pay more.
Do not script one fixed product winner for a model-directed search. The question's $800 ceiling applies **to each product**, not
to the combined purchase. Alex receives advice; the app does not purchase items
or approve a workplace expense.

Use **Reason** consistently as the third stage. Its purpose is to help Alex
decide; do not alternate stage names or promise the agent will always recommend
something. If the sources do not support the request, a qualified answer or a
clear decline is the right customer outcome. The deliberate missing-registration
fault is a different case and fails with HTTP 503.

The starting fault in each lab is intentional. Install only the current fault.
Catalog text, structured facts, vectors and evidence must describe the same
revision before using a product fact in the story.

## How to read the proof

The main Playground puts Retrieve, Rank and Reason side by side. Read one
selected search across Retrieve and Rank, then follow a recommendation's search
link from Reason. A multi-part question can call Retrieve and Rank several
times; the three columns explain responsibilities, not a single irreversible
execution sequence.

1. **Retrieve:** inspect filters, counts and how each preview product was found.
2. **Rank:** follow the same products before and after reranking. Open the
   contribution calculation to establish why their positions changed.
3. **Reason:** read the answer, compare sources, and follow a pick back to its
   saved search. Open the activity log to distinguish model-requested calls
   from deterministic controller completion.
4. **Prove within each lab:** the guided view keeps the repair checks and saved
   scorecard in an unnumbered section. They answer different questions: the
   participant's current repair versus measured quality across the test set.

In expanded details, read elapsed time as measured, not as a sum of overlapping
stages. For a plan, inspect scan type, filters, actual rows, buffers and settings.
SQL wrapped in a `plpgsql` function can appear as an opaque function scan; do
not invent an underlying index from that node alone.

Keep three questions separate, because the scorecard keeps them separate:

- **Did anything we depend on stop working?** The known-good checks.
- **How good is ranking across the whole test set?** Recall@10, MRR and nDCG@10 over twenty graded searches, shown with plain labels.
- **Did a hard filter ever leak?** Pass-or-fail checks, never averaged in.

Use the served **Compare search methods** table and the guided scorecard for
the current measurements. They read `data/evals/canonical_stage_ablation.json` and
`data/evals/canonical_scorecard.json`; do not maintain another numeric snapshot
in the presentation. Check the measurement date and build match. Show each
method alone, combined, and reranked on the same twenty graded searches.

Explain both improvements and regressions. A model reranker may help a
particular request while the average across this set gets worse. The spread of
per-search differences limits broader conclusions. A product missing from all
candidate methods cannot be recovered by reranking. The deliberately broken
lab examples prove specific failures; they are not a population-quality study.

## Architecture and authority

Use this plain-language sequence:

1. The shopper's words and filters arrive as one request.
2. Aurora evaluates three candidate searches, each applying the same eligibility filters before any limit.
3. Reciprocal rank fusion combines the three position lists into one bounded candidate pool.
4. Cohere Rerank on Amazon Bedrock reorders that pool. It cannot add to it.
5. Every run is written to Aurora with an id, so it can be read back and compared later.
6. For Ask Mosaic, a Strands agent on Amazon Bedrock plans focused searches and may call five typed tools that read the catalog. Search and agent activity still write audit records.
7. The application decides which evidence may be cited and checks the draft against product facts. If the available sources cannot support a recommendation, the response explains that limit.

The ownership line to repeat: Aurora owns retrieval truth, Bedrock models provide intelligence, and the application owns execution and citation authority. AgentCore is optional; the core labs do not require a Runtime, Gateway or Memory resource.

These stages span multiple transactions. Their persisted receipts connect the
workflow; avoid describing the complete model-and-database interaction as one
transaction.

Models pinned for the event: Cohere Embed v4 for embeddings, Cohere Rerank 3.5 for reranking, Claude Sonnet 4.6 for the agent and synthesis.

## Suggested room flow

| Time | Room activity | Checkpoint |
|---|---|---|
| 0:00–0:12 | **Introduction / Overview / Presentation** | Alex, the three lessons, architecture and the lab method |
| 0:12–0:22 | **Lab 1 — Retrieve** | Headphones return through the repaired trigram arm |
| 0:22–0:32 | **Lab 2 — Rank** | The chair leads before and after reranking |
| 0:32–0:52 | **Lab 3 — Reason**, including completion proof and takeaways | Registered evidence becomes a cited answer; all required checks pass |
| 0:52–1:00 | **Optional / flex** | Build a retrieval tool by default, Scale & HNSW as the fallback; Session & Memory as an extension when connected and rehearsed; recovery or questions |

The canonical budget is **12 + 10 + 10 + 20 + 8 = 60 minutes**. If the presentation
finishes in 10 minutes, those two minutes go to flex. Proof is included in each
lab; there is no additional mandatory five-minute conclusion that consumes flex.
Timings live in `data/evals/mosaic_labs_missions.json`.

One presenter carries Alex's story and the before/after demonstrations. The
other owns the SQL/tool explanation, monitors room progress and helps with
recovery. Both use the same checkpoints. Switch roles between labs if helpful.

If a table falls behind, use the guide's Fast track promptly. `make reset-lab-N`
reinstalls that lab's fault and restores its prerequisites; the corresponding
`make solution-lab-N` is the recovery route. Apply changed SQL and restart the
API where the guide requires it, then run the same validator. A rescue is not a
pass until its production check runs.

A catalog connection timeout is an availability problem, not a lab verdict.
Retry once, then check Aurora connectivity and database capacity before changing
the participant's code or pool settings. Keep the failed request visible so the
same action can be repeated after access is restored.

### The closing minute, within Lab 3

Keep the checked answer on screen after the completion gate. Ask one participant
for the claim, another for its source, and another for the search and rank that
brought the product into the answer. Use the existing run; do not start a new
model call to manufacture a cleaner finale.

> We restored a missing route into search, repaired the calculation behind the
> order, and made the answer use records the application could check. Alex can
> inspect the basis for the choice. In your application, replace the products
> and requirements, then keep these three questions: did the right options get
> in, can you explain the order, and what supports the answer?

Show the retrieval skill download as the take-home implementation. Only then
introduce an optional extension. Memory answers “what do we remember about
Alex?”; it does not answer “which product fact is true?”

## Optional / flex: keep the core story complete without it

The final eight minutes are optional. Pick one exercise; do not try to teach
Memory, Runtime, Gateway and HNSW as four additional labs.

**Build a retrieval tool is the default flex**, as the participant guide says:
a six-to-eight-minute command-line exercise that writes one eligibility rule,
registers one typed tool and proves Aurora applied the caller's budget. It
needs no Playground page. **Scale & HNSW is the fallback**: read-only,
deterministic, and it makes no billed call. **Session & Memory stays in the app
as an extension of the core path.** Nothing in the three labs depends on it, Playground runs and lab proofs
keep memory off, and the tab says so in its own masthead. Offer it only when the
account's Memory resource is connected and the facilitator has rehearsed it. It
extends the story after the completion gate; it never sits inside it.

### Recommended AgentCore split

| Component | What it adds | Recommended participant experience | Current release status |
|---|---|---|---|
| **Memory — user preference strategy** | Alex's preferences survive a new conversation. | A 5–7 minute flex: inspect an already extracted preference, enable saved memories in Shop, start a new conversation and inspect which record was used. | Wired: Session & Memory and Shop share the same AgentCore Memory resource. Shop starts with memory off and shows records used and save status for opted-in answers. The connection is optional and not provisioned by the base workshop stack; extraction is asynchronous; not yet rehearsed as a participant exercise in a fresh account. |
| **Runtime** | A managed place to run the existing Strands agent. | Pre-deploy if chosen. A brief architecture callout or invocation of a ready endpoint; no image build or deployment during flex. | Adapter and container source exist in `deploy/agentcore/`; an event deployment still needs rehearsal. |
| **Gateway** | A managed authenticated entry point to the agent's tools. | Pre-deploy if chosen. Show the tool boundary and one tool call; no participant IAM/OAuth setup during flex. | An optional architecture path, not a required or verified live dependency. |

Runtime and Gateway can be pre-deployed, but they are not prerequisites for
calling Memory from the existing application. Adopt them only if they make the
architecture explanation clearer and the fresh-account rehearsal passes. Aurora
continues to own retrieval scope and product evidence wherever the agent runs.
[AgentCore Gateway documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
describes the managed tool and authentication boundary.

**Do not promise that new preference extraction is instant or deterministic.**
The built-in strategy extracts and consolidates preferences asynchronously;
AWS says new insights may take a minute or more to appear. Create the Memory
resource and activate its strategy before recording the seed conversation, then
verify the extracted record before participants arrive.
[Saving and retrieving insights](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-saving-and-retrieving-insights.html)

A reliable flex has a deterministic acceptance check around that asynchronous
service: the configured account and Alex namespace return the expected record;
a new conversation uses it; the saved run identifies that record; and an
explicit current request overrides a conflicting preference. Product claims
still require catalog evidence. Preferences never become product citations.
The strategy captures preferences from conversational data; it is distinct from
Ask Mosaic's existing previous-shortlist context.
[User preference strategy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/user-preference-memory-strategy.html)

Let participants save a new preference as a stretch step and observe extraction
when it finishes. The timed exercise uses the verified seed. If readiness fails,
show a clearly labelled facilitator recording or use HNSW; do not silently replace
a missing Memory response with a hardcoded preference and call it live.

For 100+ participants, preflight every dedicated account's Memory strategy,
namespace, extracted record, permissions and model access. Rehearse the exact
write/read/new-session path repeatedly in fresh accounts, and measure its time.
No local success yet establishes room-wide capacity or a guarantee that every
new extraction will finish during flex.

**Scale & HNSW** at `/mosaic-labs/hnsw` defaults to a read-only explanation of
the index, recall versus search effort, and selective filters. It separates
current Aurora index facts from recorded measurements. The optional halfvec
and two-pass binary section reuses recorded comparisons; when attribution
differs from the current catalog or code, present those results as historical.
This interface change adds no new benchmarks or workshop-capacity evidence.

**Open advanced instrument** (`?view=bench`) uses the same open reading layout
as Hybrid retrieval and retains the live probe controls. Its rail names three sections:
**Index & storage** covers the connected cluster and recorded representation
comparisons; **Recall & filters** compares approximate search with exact
neighbors; **Scale experiments** presents projections and recorded substrate
comparisons. Pick the section that answers the question you were asked.

Keep its **Live**, **Recorded** and **Projected** labels in the explanation.
The source details for historical measurements can be expanded, but the mismatch warning stays visible.
Representation ratios use one recorded artifact, and the displayed build
parameters are labelled recorded. A live probe's server timing comes from its
second, warm execution. Neither that timing nor the halfvec comparison is a
general recommendation or evidence of concurrent workshop capacity.

### Observability without moving the ledger

Aurora is the ledger. Every run, candidate, evidence record and citation is persisted there with an id, and every Playground panel reads those rows back. Amazon Bedrock AgentCore Observability receives an aggregate projection of the same run: stage timings, candidate counts, rerank and completion status, model and token metadata, and correlation ids. It carries no product ids, no evidence text, and by default no prompt or answer content, so it holds strictly less than Aurora does and cannot become a second source of truth. It is off by default. A facilitator who wants to show it installs the optional exporter with `uv sync --extra agentcore-observability` and sets `MOSAIC_AGENTCORE_OBSERVABILITY=true`. The repository ships the AWS Distro for OpenTelemetry path for that; the application configures no exporter of its own, so where spans go is an operator choice. With the flag off, or with no recording provider installed, the adapter does nothing and Aurora telemetry is unchanged. The contract is `docs/telemetry-contract.md`, the code is `service/telemetry.py` and `service/telemetry_contract.py`.

### The same process on AgentCore Runtime

The same FastAPI and Strands process participants are running is packaged for Amazon Bedrock AgentCore Runtime behind a two-route adapter: `deploy/agentcore/app.py` mounts the service whole and adds only `GET /ping` and `POST /invocations`, the routes Runtime checks and calls. The service itself is unchanged, because the evidence authority is Aurora and not the harness. Moving where the agent loop executes does not move the ledger, the retrieval scope, or the rule about what may be cited; the same run ids come back out of the same database. If the event account has a pre-provisioned endpoint, that is a facilitator call-out, not a participant step, and no lab depends on it. The container and the adapter are in `deploy/agentcore/`; the configuration the runtime needs is documented in `docs/agentcore-runtime.md`. The ARM64 image passed a local build and grounded invocation against Aurora and Bedrock on 17 September 2026. Managed Runtime routing, IAM, and VPC attachment still need a deployed endpoint.

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
- The core agent is one bounded Strands agent with five typed, read-only tools. Cross-visit preferences are an optional Memory extension; no graph traversal is claimed.
- Aurora persists every run, candidate, evidence record and citation with an id. Ask follow-ups use prior grounded-run context. The optional Memory extension is not yet a verified event exercise. “Welcome, Alex!” alone does not establish cross-visit memory.
- Any harness that speaks MCP can call the same three tools with the same contracts. That is the answer to "does this only work with Strands".

## Words to use

Use ordinary language first and explain the mechanism where participants inspect
it. The app's copy standard is in `VOICE.md`. L400 depth comes from real SQL,
settings, ranking arithmetic, sources, failure checks and tradeoffs; participants
should not need research vocabulary to understand the result.

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
| Search summary | the saved filters, candidates, ranks and time for one request | retrieval receipt |
| Answer with sources | the answer and the records it cites | grounded answer |
| Past outcomes | completed interactions and what worked | episodes, episodic memory |
| Processing in the background | a saved message can appear before a useful memory is ready | asynchronous extraction, consolidation |

When a table asks for a model-only answer beside a grounded one, hold the model,
the prompt and the settings constant, say what context each side was given, and
never fabricate a bad answer for the ungrounded side. The contrast has to be one
a participant could reproduce.

## Before the session

Follow the event-owner preflight in the Workshop Studio repository's `FACILITATOR_GUIDE.md` end to end in a fresh event account. The steps most often skipped, and most expensive to skip:

- confirm the account can invoke all three pinned models;
- confirm readiness reports 500,000 products and 500,000 embeddings;
- check Shop at 100% browser zoom on a laptop: with Ask Mosaic open, the catalog must retain a gutter on both sides and long search questions must wrap without clipping; waiting steps must remain readable. On mobile, open Ask after scrolling and confirm its title and close action stay below the header and its follow-up box reaches the viewport bottom;
- confirm Lab 1 reads BROKEN and Labs 2 and 3 read SOLVED; rehearse the spelled control before the typo;
- seed the HNSW exact ground truth, which the cached bootstrap does not do and which Vector index at scale needs to render at all;
- run all three labs and the completion gate yourself from the rendered guide.

Treat a scorecard with mismatched source or settings as a historical measurement.
A successful source CI run and the local model rehearsals do not substitute for
fresh, attributed release measurements or a provision-to-completion rehearsal.

Beyond the guide, keep at least one replacement event account available. A broken account gets replaced; nobody improvises infrastructure at the table.

## Closing script

Lab 1 taught us that a healthy component can sit inside a broken pipeline, and that recall comes before ranking.

Lab 2 taught us that a correct answer is not proof of a correct pipeline, so ranking has to stay inspectable.

Lab 3 taught us that evidence the model has seen is not evidence it may cite, and that the application decides.

The method is:

> Find the arm that stayed silent, repair the smallest seam, run the same request again, and prove it from what Aurora recorded.

Then send them to the Prove stage: the scorecard is the same measurement on the same database, and it is theirs to take home.
