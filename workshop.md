# DAT410 Mosaic — Co-Presenter Brief

> Staff brief, written in plain language. It carries no secrets, so it is fine for a participant to find it in Code Editor. Use it to understand the story, divide presenter roles, and answer questions the same way at every table. The operational checklist lives in the Workshop Studio repository's `FACILITATOR_GUIDE.md`; this file does not repeat it.

The participant guide follows the [lab exercise design](docs/l400-lab-design.md):
every lab page has the same shape, and its four numbered tasks are the
Broken, Diagnose, Fix, Prove rhythm. The speaking cues below do not add
required exercises or change the mission contract. Use role labels in
repository material; keep the personal staffing roster outside the repo.

## The workshop in one minute

Participants are the engineers; Alex is their customer. Alex is setting up a home office for coding, video calls and focused work.

- **A reranker cannot recover a product that never entered the candidate pool.**
- **A correct-looking result can hide broken ranking.**
- **A citation must resolve to an allowed record, and its text must support the claim.**


Mosaic is a shopping catalog of 500,000 products from Electronics and Office Products in Amazon Reviews 2023. A shopper can search with keywords or ask in plain language. Both paths run against one Aurora PostgreSQL database, and both can look right while the retrieval behind them is wrong.

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

Shop's **Explore** row offers keyword, typo and intent examples drawn from the
mission manifest. All use the same pipeline. Open **Shop + search details** to
keep the storefront beside the word, spelling and meaning positions, combined
RRF position and final position. **Combined order** sorts only that table; it
does not submit a new search or replace the storefront's final order. The table
contains the displayed products, so use its Playground link for the full list.
Saved Shop searches stay in the three-column pipeline overview even when their
links name a lab example. Use **Open lab details** for the same search's full
workbench. Guide links and saved agent-proof links continue to open lab controls.
This view works with either the broken workshop state or the repaired local
state. Inject faults through the lab setup, never through a display toggle.

### First visit to Code Editor

The editor opens a rendered **Start Here** page and a ready terminal. Point
participants to the guide's first task, the source map and their learning notes.
The Explorer keeps `ui`, `service`, `db`, `scripts`, `labs`, `skills` and the
repository steering files visible. Generated files and instructor answer sheets
are hidden. The terminal stays available without a busy-task spinner.

### The spoken opening

> Alex works from home. He needs headphones for clearer calls, a chair for long days,
> and a monitor with room to run code and read docs. We have half a million products
> in Aurora PostgreSQL. Can we find suitable options, put them in a defensible
> order, and explain a choice using the sources? You will repair one failure
> in each step and prove what changed.

> We have provided the catalog, embeddings and application scaffolding. You
> will implement three critical connections in the search and evidence path,
> then use the recorded results to explain whether each change worked.

Show the source listing ID `B07G95TJ3P` beside Alex's transposed request
`B07G95T3JP`. Both use the headphones category in consumer electronics. The
correct ID retrieves Bose QuietComfort 35 II. With Lab 1's fault installed,
the mistyped ID returns other listings but misses those exact headphones.
Ask where it was lost before opening the search details. Do not imply the
other headphones lack noise cancellation: the visible error is identity.

Pin the broken search record and repeat the identical request after repair.
The target returns through Close spelling. Its Exact terms and Meaning match
positions are empty in this measured example. G-012 then checks a full-word
Bose request under the brand and category filters.

Lab 2 makes the missing option visible through a feature request: a 27-inch
4K monitor with up to 90W USB-C laptop charging. The collapsed formula drops
Dell U2720Q before the bounded reranker, while HP Z27n's title explicitly says
1440p. Repairing the rank contributions lets Dell enter the combined list;
in repeated verification it moved from combined position 24 to final position
1. Read the position from the participant's own run. Do not require it to
lead before reranking or label every other monitor unsuitable.

Lab 3 separates authorization, relevance and claim support. Registered evidence
IDs authorize citation; a separate review checks the current request and its
requirements before answer writing. Unknown device compatibility and unrelated
follow-ups decline without product cards. This review adds one bounded model
call to a supported answer, with one additional attempt if field formatting fails,
and records both calls' usage; it does not turn semantic
judgment into a deterministic guarantee.
The review returns one typed decision through Bedrock tool use. The application
checks its fields and product/source boundaries; commentary cannot substitute
for that decision, and an incomplete response cannot authorize an answer.
The headphone source checkpoint compares a Bose specification with a sampled customer review. The main
Lab 3 mission still requires separate monitor and chair searches and a comparison;
the checker reads that distinction from the mission's declared assertions.

## Introduction / Overview / Presentation

Reserve the first **10 minutes for the presentation**, regardless of how
quickly participants can open their accounts.
Do not turn this block into troubleshooting or an early start on Lab 1.

### The opening: seven beats in ten minutes

Show a customer problem before explaining its machinery. One lead carries
Alex's story; technical and Aurora presenters explain the records behind it.
Table facilitators use the same three stage questions. These are speaking cues,
not seven additional participant tasks.

State the destination during the opening: "You will repair a retrieval
capability you can use in your own agent." Carry that connection through search,
ranking and evidence. The closing downloads support that capability; skills
are packaging guidance, not another topic to teach at the end.

| Clock | Beat | Say and show | Owner |
|---|---|---|---|
| 00:00–01:00 | Meet Alex | Show the home-office brief. Alex needs clearer calls, a comfortable chair and more screen space. Ask: what would make a recommendation worth following? | Lead |
| 01:00–02:30 | A search that misses | Show the headphone control and the transposed listing-ID request with identical filters. The target disappears even though Shop still returns products. Save the broken search. | Lead |
| 02:30–04:00 | Retrieve: find the options | Show the three search methods and ask which record would locate the missing product. Filters decide eligibility; a reranker cannot add a product it never receives. Let Lab 1 establish the cause. | Technical |
| 04:00–05:30 | Rank: establish their order | Preview the question, not the next fault: if a monitor finishes first, how do we know fusion worked? Participants will write `1 / (k + rank)` fusion themselves, then propose one setting and defend it on 141 real shopper queries. | Technical |
| 05:30–07:00 | Reason: support a decision | Preview Alex's final request: the recovered 27-inch 4K monitor with up to 90W USB-C charging, and a wheeled chair with adjustable lumbar support and arms. One request needs separate searches and source comparisons. A source link must support the claim, and one reviewer's experience is not Alex's. Do not start a long agent run during the opening. | Lead |
| 07:00–08:30 | Who owns each decision? | Aurora retrieves, filters and saves records. Bedrock supplies embeddings, reranking and the agent model. The application validates tool calls and citations. Read-only catalog tools still produce audit writes. Show one saved search ID, not a service tour. | Aurora presenter |
| 08:30–10:00 | Your work and its proof | Explain the provided scaffolding and the three connections participants implement. Open the guide and the two work surfaces. Predict, observe, diagnose, repair, repeat the same request, explain the change. Each lab has one graded piece of work participants write themselves. Required work finishes by minute 50. | Lead |

The slides introduce a question; each lab answers it with real records. Keep
SQL, plans, budgets and measured comparisons beside the relevant proof instead
of front-loading them into the opening.

### Three expert discussions inside the existing proof time

Use these as short presenter questions while participants inspect the existing
records. They do not add a required query, repair or validation command. Start
with the participant's prediction and finish with the observed result.

| Stage | Ask | Read together | Limit the conclusion |
|---|---|---|---|
| Retrieve | The filters are correct. Why might vector search still return too few eligible products? | Applied filters, returned counts, and an available recorded plan with scan settings, rows and buffers | Eligibility does not establish coverage. HNSW can visit rows that fail the filter; iterative scanning explores further within its limits. An opaque function scan does not reveal its underlying index. |
| Rank | The final winner looks right. What proves fusion worked, and what justifies the reranker? | Different source ranks, their RRF contributions, earlier and final positions, and the served measured comparison | A correct winner cannot certify the formula. Read improvements and regressions across the graded searches; fixing RRF alone saves no model call. |
| Reason | The citation opens. Which words support this particular requirement? | One claim, its source type and revision, the product, and its recorded search | A specification and a review answer different questions. Registration permits citation; it does not establish claim support. Say what remains unknown. |

In Reason, also point to two actual search requests and their filters. Identify
which calls the model requested and which application code started. The main
Playground's **Answer and sources** reports these separately, with **Origin not
recorded** for older steps that lack this field. Tool activity records actions;
it is not a transcript of private model reasoning. One compound question can
repeat Retrieve and Rank before an answer is supported.

If time is tight, use the current records and one question per stage. Do not
launch another agent run or open the full HNSW exercise to fill a speaking cue.

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
and monitor are still to choose. The portrait and brief establish the customer;
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
| **More screen space** | Alex needs code and reference material visible together. | Screen size, resolution, and separate confirmation of USB-C video and laptop charging. | Find monitors for Alex → monitor search and comparison. |

Lab 3 carries forward the monitor requirements from Lab 2 and adds an
adjustable chair. Search each category separately. Inspect Dell U2720Q and
Steelcase Gesture against the source records, and state what the available
reviews do not establish. No chair specification proves personal comfort
through a full workday. The evidence-registration repair stays the same.

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

1. Open three browser tabs from the Event Dashboard: Code Editor and Mosaic, plus the guide itself. The introduction shows one healthy meaning-only search and the three names Shop prints for its searches.
2. Lab 1, Tasks 1a to 1d (explain a mechanism): see Bose QuietComfort 35 II disappear for a transposed listing ID; derive from `websearch_to_tsquery`, `show_trgm` and `word_similarity` why word search cannot match and close spelling can; rebuild the close-spelling method from its contract; then write a recall query for the filtered vector search. The grader runs it with the planner's plan (an exact btree scan) and with HNSW forced, where the obvious "exact" query is itself served by the index. Index construction and tuning are the optional Scale & HNSW flex exercise.
3. Lab 2, Tasks 2a to 2d (write an algorithm): write RRF in SQL over the three installed search functions, graded at five values of `k`; find that the saved run has two distinct scores, so the `product_id` tie-breaker decided the reranking cutoff; repair production to agree with your query; then propose one setting change with a rule stated in advance, have it replayed over 141 ESCI judged queries and four reviewed chair controls, and adopt or reject it as the rule says. On 2026-09-22, a cutoff of 75 admitted 24 more Exact products (18 queries better, 0 worse) in the same billed rerank unit, while `k`=120 admitted 5 more (4 better, 0 worse, p=0.125) and moved one chair control from 3rd to 4th.
4. Lab 3, Tasks 3a to 3d (specify a contract): read the fail-closed HTTP 503; trace evidence to the state that authorizes citations; write tests that must reject four faulty implementations, then repair `register_evidence` and restart; resolve every citation; write a claims query that separates the evidence the answer cited from reviews merely imported and the source's rating count; close the loop with a query showing the agent's own searches used the Lab 1 and Lab 2 repairs.
5. Run the completion gate inside Lab 3, then **bring Alex's office home**: one query assembles his room from the participant's three saved runs (the repair behind each item, how it was found, its source rating count, sampled reviews and historical list price). Then use the remaining time for an optional exercise, catch-up or questions.

Each lab has a manual path and an optional coding-agent path (`claude` from the repository root, with guardrails). Both must meet the same contract and pass the same grader and validator. There is no fast track; Hint 4 restores the repair without printing it, and the graded exercise stays on every path.

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
- **Shop.** The default Workspace edit shows a curated selection of the imported catalog; keyword search reaches the full 500,000 products. Every result card can open "See how this was retrieved", carrying the query, filters and saved search event into the Playground. Ticking two or more results compares them side by side, and the comparison is worth showing: under the price and the rating it prints which search methods found each product, its rank before reranking, and the rank the shopper was shown. Those three rows come from the run's saved receipt, not from the list on screen, which is why a comparison is only offered once a search has run. If the catalog carries none of a request's words, Shop says which ones above the results rather than returning a confident page of near misses.
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

Guide links use `view=lab` on `/labs/retrieval` for the exercise detail. Shop
links carry their saved search event into the three-stage Playground, preserving
the request and both ranking orders. The current catalog serves unchanged source
listings from Amazon Reviews 2023. Product pages retain original listing links,
source image links, historical rating aggregates and explicit unknown values.
Neither a relevance label nor a matching model number establishes compatibility.

Workshop Studio restores the selected 500,000 records and saved vectors from the
hash-pinned real-catalog bundle, then sets `MOSAIC_CATALOG_DATASET`. The original
cached catalog remains for shared schema setup and historical optional benchmarks;
it is not the Shop catalog. The 32 imported review excerpts cover a reviewed
subset. Lab 3 distinguishes specifications from reviews and admits missing
excerpts rather than treating a rating count as review text. The bundle is local;
public redistribution clearance and fresh-account delivery proof remain separate
release requirements.

Shop introduces Alex beside a compact title, then shows three large scenes:
headphones for focus, a chair for comfort, and the complete workspace. Their
Retrieve → Rank → Reason labels follow the core mission order; the captions
tell the shopping story without giving exercise instructions. Search and Ask
sit immediately below. The scenes scroll horizontally on mobile and step
aside during a search or an open Ask conversation.

Explore and Ask follow the canonical Hybrid retrieval request order: **Clearer calls**,
**Comfortable days** and **More screen space**. Exact listing identity is checked inside Lab 1.

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
Saved tool calls retain their execution sequence even when Aurora assigns them
the same transaction timestamp. A rejected synthesis attempt has no citations;
completion replay checks the successful answer that followed it.

## The three-lab journey

| Lab | What Alex sees before | What is broken | PostgreSQL and model mechanisms | What the participant writes (graded) | What proves it |
|---|---|---|---|---|---|
| **Retrieve — 10 min** | The transposed listing ID loses the exact Bose headphones. | Close-spelling results never enter fusion. | PostgreSQL FTS, `pg_trgm`, pgvector and SQL filters; the planner's choice between an exact scan and HNSW. | The trigram CTE and channel, from a contract; a recall query graded under the planner's plan and forced HNSW, whose obvious "exact" set is itself served by the index. | The Bose listing returns through close spelling; controls pass; the recall instrument passes. |
| **Rank — 10 min** | The suitable Dell is absent; an explicitly 1440p monitor appears for a 4K request. | Every source position receives rank-1 credit, so the `product_id` tie-break picks the shortlist. | RRF combines positions; Cohere Rerank reorders the bounded list. | RRF in SQL, graded at five values of `k`; then one retrieval change with a pre-stated rule, replayed over 141 ESCI judged queries and four reviewed chair controls. Adopting and rejecting both pass. | Dell enters the list; the saved run agrees with the participant's fusion; the decision follows its own rule. |
| **Reason — 20 min** | Products and sources are found, but a cited answer cannot be produced. | Evidence IDs are not registered in application state. | Typed tools, separate searches, Aurora evidence and citation checks. | Contract tests that must reject four faulty implementations, then the repair; a claims query separating cited evidence from imported reviews and source rating counts. | Resolvable citations; the loop query shows the Lab 1 and 2 repairs in the agent's own searches. |

**Retrieve:** reranking cannot recover a product outside its input list.
**Rank:** the formula and the final order answer different questions. Correct
fusion gives reranking a better input list; it does not remove the model call
or establish latency savings. **Reason:** registering a source establishes
which record may be cited; its text must also support the particular claim.

**Filters deserve their own explanation.** Each SQL arm applies eligibility
before its candidate limit. Eligibility and the limit are two budgets, and
neither gets to change the other. That does not mean an HNSW graph only visits eligible
rows: selective filters can leave an approximate scan short, and iterative scans
may need to explore further. Inspect both eligibility and candidate count.

Use the Bose brand/category control to inspect all saved products, including
those outside the first page. Eligibility is a requirement before ranking;
a high model score cannot waive it.

### The handoffs: one customer, increasingly demanding questions

| Transition | Spoken bridge | What carries forward |
|---|---|---|
| Retrieve → Rank | “We can find the exact headphones Alex meant. Now he needs room for code and docs, with one cable to his laptop. Can combining good search results still lose the right monitor?” | The repaired retrieval path, with a new request |
| Rank → Reason | “The monitor now reaches the shortlist. Let's check its specifications and add a chair. Which facts support each choice, and what remains unknown?” | The monitor requirements and repaired ranking, with fresh searches in both categories |
| Reason → decision | “Pick one claim. Show the source, the product, and the search that brought it into the answer.” | A choice backed by inspectable records |

Dell's record supports 27 inches, 3840 x 2160 and USB-C power delivery up to
90W. Steelcase Gesture's record names adjustable lumbar support and movable
arms. Those facts support a comparison; they do not guarantee compatibility
with an unspecified laptop or individual comfort. Do not invent current prices,
stock, review text or a 12-hour comfort rating. Lab 3 does not consume a saved
Lab 2 selection, and the required path uses no cross-session memory.

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
execution sequence. Each column uses the same arrangement: summary, product
cards, notes, lesson and inspection control. Reason keeps all recommendations
together; expand **Read Mosaic’s full answer** for the complete explanation.

1. **Retrieve:** inspect filters, counts and how each preview product was found.
2. **Rank:** follow the same products before and after reranking. Open the
   contribution calculation to establish why their positions changed.
3. **Reason:** read the answer, compare sources, and follow a pick back to its
   saved search. Open the activity log to distinguish model-requested calls
   from deterministic controller completion.
4. **Prove within each lab:** the guided view keeps the repair checks and saved
   scorecard in an unnumbered section. They answer different questions: the
   participant's current repair versus measured quality across the test set.

In expanded details, distinguish the recorded search request time from the
database retrieval stage, which includes the application's database round trip.
Embedding time may include a cache lookup. The recorded stages do not sum to the
total, and generating the agent's answer takes additional time.

**View retrieval event** reads saved ranks and the original environment; its
candidate eligibility check uses the current catalog. **Run EXPLAIN ANALYZE**
executes SQL again with the saved query, filters and search settings, current
functions and data, and the configured query embedding provider. It replaces
the saved plan without changing the original candidate ranks. Read estimated
and actual rows per loop, loops, planning and execution time, buffers and settings.
Buffer counts at the top node include child work; do not add them again.
SQL wrapped in a `plpgsql` function can appear as an opaque Function Scan; the
summary lists only index names actually visible in the plan. It does not infer
the indexes used inside the function.

For the answer, check the meaning of a measurement as well as its number and
unit. Battery life does not establish recommended daily use. Mosaic rejects
that substitution even when the citation resolves to the correct product;
the source walkthrough should make the same distinction.

Keep three questions separate, because the scorecard keeps them separate:

- **Did anything we depend on stop working?** The known-good checks.
- **How good is ranking across the whole test set?** a separate, representative set of independently judged requests.
- **Did a hard filter ever leak?** Pass-or-fail checks, never averaged in.

The earlier 20-search scorecard and 720 generated filter cases belong to the
synthetic catalog. They do not certify the imported dataset. Keep historical
averages hidden as current results until a new benchmark is measured. The
required lab checks validate the repaired examples and five controls.

The [worked-example library](docs/real-catalog-exercise-library.md) records 14
paired requests, including unchanged winners and a wording variant that still
misses the monitor. Six listing-ID errors recover across three categories. This
is broader teaching coverage, not a random sample of all 500,000 products.
Choose examples for a clear mechanism; preserve failures when discussing quality.

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

Models pinned for the event: Cohere Embed v4 for embeddings, Cohere Rerank 3.5 for reranking, Claude Sonnet 5 for the agent and synthesis.

## Suggested room flow

| Time | Room activity | Checkpoint |
|---|---|---|
| 0:00–0:10 | **Introduction / Overview / Presentation** | Alex, the three lessons, architecture and the lab method |
| 0:10–0:20 | **Lab 1 — Retrieve** | Headphones return through the repaired trigram arm |
| 0:20–0:30 | **Lab 2 — Rank** | Dell enters the combined list and rises after reranking |
| 0:30–0:50 | **Lab 3 — Reason**, including completion proof and takeaways | Registered evidence becomes a cited answer; all required checks pass |
| 0:50–1:00 | **Optional / flex** | Build a retrieval tool by default, Scale & HNSW as the fallback; recovery or questions |

The canonical budget is **10 + 10 + 10 + 20 + 10 = 60 minutes**. Proof is included in each
lab; there is no additional mandatory five-minute conclusion that consumes flex.
Timings live in `data/evals/mosaic_labs_missions.json`.

One lead carries Alex's story, the clock and the projected browser. Assign SQL,
agent evidence and room support roles before delivery. Use the role table below
to make each handoff explicit; a presenter joins for the relevant proof and then
returns control to the lead. Keep the same stage questions at every table.

If a table falls behind on an edit, use the guide's Hint 4 recovery promptly; keep the graded exercise. `make reset-lab-N`
reinstalls that lab's fault and restores its prerequisites; the corresponding
`make solution-lab-N` is the recovery route. Apply changed SQL and restart the
API where the guide requires it, then run the same validator. A rescue is not a
pass until its production check runs.

A catalog connection timeout is an availability problem, not a lab verdict.
Retry once, then check Aurora connectivity and database capacity before changing
the participant's code or pool settings. Keep the failed request visible so the
same action can be repeated after access is restored.

### The closing minute, within Lab 3

After the completion gate, run **Bring Alex's office home** from the
Conclusion. One query assembles Alex's room from the participant's own saved
runs: for each item, where it was before and after the repair, the methods that
found it, the specifications and reviews the answer cited, the reviews imported
and the source's rating count. A second query reads back the participant's Lab 2
decision from `mosaic.lab_decision`. Measured on 2026-09-22: the Bose has 5,341
source ratings and 18 imported reviews, the Dell 6 and 2, the Steelcase 1 and 1.
Ask one participant for a claim, another for its source, and another for what
Alex still needs to check. Use the existing runs; do not start a new model call
to manufacture a cleaner finale.

> We restored a missing route into search, repaired the calculation behind the
> order, and made the answer use records the application could check. Alex can
> inspect the basis for the choice. In your application, replace the products
> and requirements, then keep these three questions: did the right options get
> in, can you explain the order, and what supports the answer?

Close with **Use what you built in your own agent**. Show **Adapt the
implementation** for the SQL and the map to evaluations and citation checks,
and **Download the skill** for calling instructions and API mappings. Keep the
full checkout for the runnable reference; the skill calls its running service.
Then introduce an optional extension. Memory answers “what do we remember about
Alex?”; it does not answer “which product fact is true?”

## Optional / flex: keep the core story complete without it

The final ten minutes are optional. Pick one exercise; do not try to teach
Memory, Runtime, Gateway and HNSW as four additional labs.

**Build a retrieval tool is the default flex**, as the participant guide says:
a six-to-eight-minute command-line exercise that writes one eligibility rule,
registers one typed tool and proves Aurora applied the caller's budget. It
needs no Playground page. **Scale & HNSW · shrink it is the alternative**:
participants write a partial HNSW index for headphones (full precision,
`halfvec` or binary quantization) and the query that uses it;
`scripts/flex_exercise.py` builds it twice in a rolled-back transaction and
grades mean recall over five real shopper queries, time against the exact plan,
and size against a full-precision reference. It makes no billed call. Measured
on 2026-09-22: `halfvec` kept recall 0.989 at 33% of the reference size; binary
codes with a 1,000-row re-sort kept 0.945 at 5%; a `halfvec` index with an
unrewritten query was never used. Open the HNSW graph only to explain the
mechanism.
**Session & Memory stays in the app
as an extension of the core path.** Nothing in the three labs depends on it, Playground runs and lab proofs
keep memory off, and the tab says so in its own masthead. Offer it only when the
account's Memory resource is connected and the facilitator has rehearsed it. It
extends the story after the required hour; it never sits inside it.

### Recommended AgentCore split

| Component | What it adds | Recommended participant experience | Current release status |
|---|---|---|---|
| **Memory — user preference strategy** | Alex's preferences survive a new conversation. | Optional Lab 4 after the hour: save Alex's monitor preference, inspect the actual extracted record, recall it in a new conversation, follow fresh product evidence, change today's request and check another actor's isolation. | Wired: Session & Memory and Shop share the same AgentCore Memory resource. Shop starts with memory off and shows records used and save status for opted-in answers. The connection is optional and not provisioned by the base workshop stack; extraction is asynchronous; not yet rehearsed as a participant exercise in a fresh account. |
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

**Full benchmark workbench** (`?view=bench`) uses the same open reading layout
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

Assign people outside the repository. These are responsibilities, not additional
talk slots; one person can cover more than one role.

| Role | Owns | Handoff or review question |
|---|---|---|
| Lead presenter | Customer story, clock, projected browser and transitions | What changed for Alex, and what record demonstrates it? |
| SQL presenter | Candidate paths, filtering, fusion arithmetic and plan reading | Does the SQL or plan support the database claim? |
| Agent presenter | Tool decisions, application checks, source comparison and claim support | Which action did the model request, and what could the application refuse? |
| Room support | Navigation, syntax recovery, grader and validator outcomes, and Hint 4 pacing | Can the participant explain the repair using their own result? |
| Technical reviewer | Challenge the database, ranking and answer claims during rehearsal | Does the plan support the claim, does the measurement justify the ranking decision, and does the source support the answer? |

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

## Required depth and one connected story

Follow [the L400 teaching contract](docs/l400-lab-design.md). Each lab opens with
Alex's next need and the architecture boundary under investigation. Ask for a
hypothesis before hints. A small patch is deliberate; the required work includes
a measured counterexample and an explanation of what the result does not prove.

Labs 1 and 2 center on `psql` in the Code Terminal. A small runner saves the
real application response and loads its IDs and parameters for SQL inspection.
Lab 1 explains each search method from PostgreSQL's own functions and grades a
recall instrument under two plans. Lab 2 grades participant-written fusion and a
one-setting proposal judged on 141 real shopper queries. Lab 3 grades contract
tests against faulty implementations and a query that separates cited evidence
from available evidence, then closes Alex's brief from Aurora. Every graded
attempt is saved in `mosaic.lab_decision`, which the finale reads.
Keep 10/10/20 minutes for the three labs; use recovery to protect the proof.
Do not call the session room-tested until a timed human run confirms that pace.

Lab 3 checks registration behavior, not whether a participant copied the
reference answer's structure. Different local names or a product-list lookup
outside the loop are valid when the same evidence contract holds. A broken or
non-terminating function fails the bounded source check; the end-to-end validator
still checks retrieval, recommendations and citations.

## What staff should remember

- The copied-ID transposition is a narrow identity-recovery case. Inspect the direct methods: only the restored trigram arm found this target in verification. Do not generalize that result to brand misspellings or all semantic searches.
- Filters are applied inside every search arm before any limit. They are never a reranker hint.
- Raw full-text, trigram, vector, fusion and rerank scores do not share a scale. That is why fusion uses positions.
- The reranker receives a bounded pool. It does not replace retrieval.
- The core agent is one bounded Strands agent with five typed, read-only tools. Cross-visit preferences are an optional Memory extension; no graph traversal is claimed.
- Aurora persists every run, candidate, evidence record and citation with an id. Ask follow-ups use prior grounded-run context. The optional Memory extension is not yet a verified event exercise. “Welcome, Alex!” alone does not establish cross-visit memory.
- An MCP-capable agent can use the three typed catalog-read-only tools on that
  surface. The downloadable HTTP skill exposes four operations. Read each
  surface's declared contract rather than assuming identical tool sets.

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

Lab 3 taught us that the application controls which evidence may be cited, and
that the cited text must still support the particular claim: one reviewer's
MacBook Pro charging is not Alex's laptop.

The method is:

> Find the arm that stayed silent, repair the smallest seam, run the same request again, and prove it from what Aurora recorded.

Finish on the checked answer and trace one claim back to its source, product
and search. The completion gate rechecks the participant's saved runs; the
broader scorecard is a separately dated measurement. Close with **Take hybrid agentic search into your own agent**. Download the
skill from the Labs completion panel and carry forward the full workflow:
`tsvector` + `pg_trgm` + `pgvector` → RRF → Cohere Rerank → answers with sources.
The package includes checks for filters, recall, ranking and citations. Any agent
can read the instructions and connect the four declared HTTP operations; its
application must retain the answer and citation checks. The skill does not host
the catalog, and the temporary event backend expires with the workshop.
