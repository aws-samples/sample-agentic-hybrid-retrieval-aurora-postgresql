# Alex's needs, Mosaic at catalog scale

Status: the local Shop serves `reviews-2023-v2`, with 553,911 imported
records and embeddings. The required requests are defined by the active mission
contract. The [hybrid-search review](hybrid-search-design.md) records current
category corrections, SQL comparisons and served searches. Broader quality,
vector-representation comparisons, source release, Workshop Studio publication
and a fresh participant environment remain separate proof boundaries.

The [typo readiness spot check](evidence/real-catalog-typo-readiness-2026-09-20.md)
found that the requested misspelling works through the existing generated
catalog's trigram path, but two reviewed public headphone records fall below
the current word-similarity gate when tested as preserved source text. The
September 21 [paired search observations](evidence/catalog-source-audit/search-validation-2026-09-21.json)
confirmed that the old typo request returned the same leading three products
with spelling search enabled and disabled. A model-name typo also preserved its
leading three. Neither earned the Lab 1 demonstration. The current exercise uses
a transposed real listing ID instead. Any replacement example must show
an independently reviewed feature or identity failure that the repair actually
fixes, with unchanged source descriptions and the same request in both states.

## The opening

Meet Alex. Software engineer. Works from home.

> “I've got the desk and the laptop. Now I need a setup I can actually work in,
> every day.”

He wants headphones for clear calls and fewer distractions, a chair with support
he can adjust, and enough screen space for code and documentation side by side.
Start with a need participants can recognize and a feature they can check.
Keep the product photograph, exact model, requested feature and source visible
together. A photograph alone cannot establish noise cancellation or USB-C power
delivery.

Alex also gives us an engineering perspective. Once the search helps him make
a choice, the next question is: **“Can we keep this useful and fast across the
whole catalog?”** The story grows from a specific need into operating a search
system. It does not require Alex to buy an ever-growing list of unrelated items.

## The three-part progression

| Part | Alex's question | Builder's responsibility | Evidence to leave with |
| --- | --- | --- | --- |
| Retrieve | “Can I find the headphones I mean, even when I mistype the name?” | Combine exact terms, close spelling and meaning; apply product-type and feature requirements inside the retrieval paths. | A relevant product appears for the intended reason, and an accessory is not treated as the requested product. Show the matching source fields and search-method contributions. |
| Rank | “Which options actually fit my needs—and can this work across the full catalog?” | Combine source positions correctly with RRF, inspect model-based reranking, and retain the right monitor before the bounded rerank cutoff. | Explain both why a product moved and whether a storage or search setting lost relevant options before ranking. Preserve the same request and filters for each comparison. |
| Reason | “Help me finish the setup. Compare the remaining options and tell me what the evidence supports.” | Use focused searches, product specifications and selected reviews; retain the earlier requirements; synthesize an answer with resolvable sources. | A recommendation distinguishes established features, reported experiences and missing information. Every cited claim resolves to the correct product and source record. |

Lab 2 checks the monitor; Lab 3 brings that decision together with an adjustable chair, without promising personal comfort. The monitor adds a useful dependency: screen size and resolution are not enough; the connection must also
support the intended laptop workflow. Do not imply that USB-C alone guarantees
video, laptop charging or a particular charging wattage.

Keep Alex's chair consistent across the hero, walkthrough and recommendation:
the room shows a wheeled chair and the reviewed Steelcase listing specifies
casters. The room is an illustration, not a photograph of that exact listing.
The optional ESCI query about a chair without wheels belongs to another
customer; it must not become Alex's preference or require a different hero.

The last part should refer back to the earlier requirements and decisions.
Explicitly state whether this context came from the active conversation or from
a verified memory read. Do not label ordinary chat history as AgentCore Memory,
and do not present remembered preferences as product evidence.

## The scale checkpoint (optional after completion)

The core comparison uses prebuilt indexes and a short, repeatable request set.
Index construction and broad parameter sweeps remain an extension. Preserve the
60-minute session budget and its contingency; do not make every participant
wait for three index builds.

The existing mission contract remains the single source for timings and
settings. The new scale checkpoint should replace optional comparison time
when the contract is updated, rather than silently lengthening the session.

| Representation | What changes | What builders must check |
| --- | --- | --- |
| `vector` | Full-precision values provide the reference representation. | Obtain exact filtered neighbors separately from approximate HNSW results. A full-precision HNSW index is still approximate. |
| `halfvec` | The existing embedding is converted to 16-bit values. | Measure index size, end-to-end query latency and agreement with the exact full-precision result set. |
| Binary values plus full-precision rescore | Sign bits support a compact approximate search; full vectors rescore the returned rows. | Include both passes in latency, vary the number of rows carried into the second pass, and report any remaining loss. The original full vectors must remain available. |

Do not regenerate embeddings for these representation changes. Keep embedding
model, source text and dimension constant. Existing implementation references
are `db/sql/19_indexes_quantized.sql`, `scripts/benchmark_mosaic_scale.py` and
`docs/benchmark-methodology.md`; check which production paths each measurement
exercises when implementing the checkpoint.

Use two distinct quality checks:

- **Did we preserve nearest neighbors?** Compare approximate results with exact
  full-precision results under identical filters. Explain this before naming
  Recall@k. Record the result count as well as the fraction recovered.
- **Did we answer the shopping request?** Check independently reviewed product
  requirements and source evidence. Agreement with a vector result set does not
  by itself establish useful product recommendations.

Use representative requests from the broader Electronics and Office Products
catalog for the scale comparison. Include narrow filters and both exact-model
and intent requests. Keep Alex's reviewed requests visible as understandable
controls, and keep additional evaluation requests separate from the examples
used to tune settings. Do not claim that the current two-department selection
represents every retail category.

Record source selection hash, embedding model, database and extension versions,
ACU settings, effective retrieval settings, index sizes, build times, filter
selectivity, result counts and latency distribution. Separate cold and warm
measurements. Do not reuse the old synthetic-catalog scorecard or the AWS blog's
numbers as measurements of the new product corpus.

## Keep the stages in the same order everywhere

The diagram, SQL, app trace and spoken explanation must agree:

1. Apply the request's requirements and retrieve rows through full-text,
   spelling and vector search.
2. If the selected vector path uses binary search, rescore its returned rows
   with the original vectors before treating that path as a ranked input.
3. Combine the search-method positions using reciprocal rank fusion.
4. Apply the model-based reranker to the bounded combined list.
5. Let the agent gather specifications and reviews for the resulting choices,
   compare them and produce an answer with sources.

Full-precision vector rescoring and model-based reranking must have different
labels. Neither can recover a product that never reached its input. A smaller
index is not sufficient evidence that the full request became faster or cheaper.

## Reviewed examples and source limits

`data/real-catalog-examples.json` records the reviewed examples and their source
identities. The local preview contains five headphones, five chairs and six
monitors. Ten are verified members of the selected real-product corpus;
`selected_in_bulk` records that membership in the example registry. The original six use
ESCI variant identities and retain their specification links. Five require
parent-product mapping before Reviews 2023 ratings or reviews can be attached.
One exact parent ID was found in the full metadata but was not selected by the
initial sample. Do not silently substitute a renewed item, bundle, color or
microphone variant.

The selected samples now support three concrete comparisons before retrieval
testing is complete:

- Headphones: the Bose listing documents cancellation and call microphones;
  the Soundcore listing leaves call support unestablished; GEEKRIA is an
  accessory even though its title names compatible headphones.
- Chairs: Steelcase documents movable arms and adjustable lumbar support;
  adjustable seat height alone does not establish the Amazon Basics chair's
  other adjustments; a chair mat is not a chair.
- Monitors: the selected Dell U2720Q-Black record documents 27 inches, 4K,
  USB-C video and up to 90 W power delivery. The other selected controls expose
  a resolution mismatch or undocumented charging. The exact parent ID is
  `B0939N79Y8`; it is not the original unselected Dell identity. Laptop and
  cable compatibility still need checking.

Use the preview's Gallery and Compare features views to inspect these source
differences. Select **Selected catalog only** to exclude the reference samples.
**Documented fits only** requires every listed requirement to be supported;
missing information stays **Needs verification**, distinct from a known
mismatch. These controls compare supplied facts; they neither run retrieval
nor prove the replacement lab fails and repairs correctly. Keep the existing
captures tied to their measured source revision; never present an old-catalog
recording as a run over these imported records.

Examples serve different purposes: a documented fit, a known mismatch, an
accessory, or an unanswered requirement. Missing documentation is not proof
that a feature is absent. Exclude contradictory records from the main teaching
examples, retain their source text unchanged, and record the reason for the
exclusion.

The new metadata supplies historical rating aggregates for all selected
products. Individual review text is separate evidence. Preserve the aggregate
rating; do not replace it with the average of a small chosen set of reviews.
The source does not supply live availability, and many records have no price.
Retire current-stock and universal-budget claims unless the replacement data
actually supports them.

## Optional Part 4: remember Alex's preferences across visits

Keep this outside the required Retrieve, Rank and Reason sequence. It can reuse
Alex and Mosaic while teaching a separate question: **what should an assistant
remember when a person starts a new conversation?** It does not demonstrate
vector-index scale, and completing the retrieval labs does not certify a
production deployment. Do not consume the session's recovery time or promise
a completion time before a participant rehearsal.

Use AgentCore Memory for the first extension. Runtime and Gateway are independent
deployment and tool-access choices; neither is a prerequisite for this exercise.

| Component | Question it answers | Place in the extension |
| --- | --- | --- |
| Aurora PostgreSQL | Which products meet this request, and what records support the answer? | Keep the existing SQL, filters, search, ranking and answer records. |
| AgentCore Memory | Which preferences did this person share in an earlier conversation? | Retrieve the current actor's saved preferences as context for a fresh search. |
| AgentCore Runtime | Where does the agent execute, and how is its execution session isolated? | A separate deployment exercise after the Memory extension is validated. |
| AgentCore Gateway | How does an agent discover and call tools through a managed MCP endpoint? | An alternative advanced exercise when tool access itself is the learning objective. |

Aurora can store conversation history and application preferences. The reason
to demonstrate AgentCore Memory is its managed extraction and retrieval of
useful conversational context, not a claim that PostgreSQL cannot persist it.
Memory supplies Alex's preferences; product records and source evidence still
establish what a product can do. Product embeddings do not change for this lab.

### Participant sequence

1. In one conversation, Alex states a preference such as a 27-inch monitor with
   laptop charging over USB-C. Save his actual message and inspect the event.
2. Inspect an extracted preference record before proceeding. An accepted event
   and an active Memory resource do not establish that extraction completed.
3. Start a new session for the same actor, with no copied shortlist or previous
   messages. Ask for a monitor recommendation and compare memory off with an
   opted-in request. Inspect the record IDs actually used; a plausible answer
   alone does not prove a memory read.
4. Follow the fresh Aurora searches and product evidence. A remembered desire
   for USB-C charging must not establish that a particular monitor supports it.
5. Change the request explicitly and verify that it takes precedence over the
   older preference. Start with a different actor and verify that Alex's saved
   records are unavailable to that actor.

The technical sequence is event capture (`CreateEvent`), asynchronous extraction,
inspection (`ListMemoryRecords`), a new session, actor-scoped recall
(`RetrieveMemoryRecords`), and fresh Aurora retrieval. Use this same order in
the guide, architecture diagram, code, UI demonstration and speaker notes.

[AWS documents extraction as asynchronous](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html).
Pre-provision the resource and rehearse with real earlier events. A prepared
example must be identified as prepared; never invent a memory record or claim
that a fixed sleep guarantees extraction. If the participant's record is not
available, show that state and continue with the inspected prepared example.

### Existing implementation and remaining proof

`service/session_memory.py`, the Session & Memory Playground, and Ask Mosaic's
opt-in memory control provide an implementation starting point. The application
already scopes records by actor, checks session ownership, records which
memories were read, and keeps memory outside the product citation allowlist.
See [Session & Memory](session-memory.md). The live-service rehearsal below
verifies this flow on the existing catalog; it does not establish acceptance of
the public-catalog replacement or a fresh participant deployment.

The Runtime adapter also exists, but the managed endpoint, identity mapping,
IAM permissions and Aurora network path need deployment proof. Its current
`/invocations` route does not accept the browser identity used by the Memory
flow; combining the two requires an explicit authenticated identity design.
Runtime sessions and durable cross-session preferences are separate concerns;
[AWS makes that distinction explicit](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
See [AgentCore Runtime](agentcore-runtime.md).

For a Gateway exercise, discover tools with `tools/list` and invoke the exact
returned name. The documented MCP name is `${target_name}___${tool_name}` with
three underscores. For API Gateway targets, `operationId` supplies the tool
name by default, and an override can change it. Do not generalize
`${targetName}___${operationId}` to every target type. Include a failing call
with the unprefixed name and a successful call with the discovered name, without
changing the underlying search implementation. Sources:
[Gateway tool naming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)
and [API Gateway target names](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-api-gateway.html).
This naming rule has been checked against the documentation; a Mosaic Gateway
deployment and invocation have not been validated for this extension.

The 20 September rehearsal proved event capture, actual extraction, recall in a
new session without prior events, current-request precedence, cross-actor
isolation and fresh product evidence on the existing live catalog. Provider-error
visibility and memory opt-out remain covered by the production-path unit tests.
The optional exercise now lives under `optional_labs.memory` in the mission
contract and in the Session & Memory UI. See the [rehearsal record](evidence/workshop-rehearsal-2026-09-20.md).

The public-catalog version still needs its own retrieval and source-evidence
acceptance after embedding import. Keep the required labs usable with memory
off. Test actors are isolated; starting fresh does not delete their saved
records. Resource-wide cleanup, fresh-account provisioning and Workshop Studio
publication are separate release checks. This design document is not a timing
contract.

## Presenter transitions

**Opening:** “Alex has the desk and laptop. What he needs next is familiar:
clear calls, a chair he can adjust and room for code and documentation. We are
going to help him make those choices, then inspect the database work that made
the answers possible. Keep an eye on the requested features—we should be able
to point to a product record that supports every one.”

**Retrieve to rank:** “Finding something is only the first test. A headphone
case can repeat all the right model names. A chair can sound comfortable
without documenting the adjustment Alex needs. Now that we can inspect where
the results came from, we will check which products remain eligible and why
their positions change.”

**Rank to scale:** “Alex is an engineer too. He now asks what this costs when
we search the whole catalog. We will keep the request and filters fixed and
change how the vector index represents each product. Watch three things:
which products we keep, how long the complete request takes and how much index
space it uses. Smaller is useful only when the measured trade-off is acceptable.”

**Scale to reason:** “A fast search still does not make a decision for Alex.
The agent needs to check the remaining requirements, compare the product
specifications with people's reported experiences and explain any gaps.
Earlier choices give it context; source records give it evidence. The final
answer should make that distinction clear.”

**Reason to optional memory:** “Alex comes back another day. He should not have
to repeat every preference, but we still need to check each product against
its source records. This optional extension separates those responsibilities:
Memory recalls what Alex told us, and Aurora searches the catalog again. We
will inspect what was remembered, verify that a new request takes priority,
and check that another person cannot read Alex's preferences.”

## Acceptance before replacing the live workshop

- Confirm exact product and variant identities, original text, original photos
  and the source of every normalized feature used in a lab.
- Prove the proposed failure through the actual broken production path, then
  prove the repair using the same request and data. Reject an example if it
  already passes without the intended fix; do not rewrite source descriptions
  to force a result.
- Complete the new embeddings and index measurements in Aurora, including
  filtered exact reference results and the current resource configuration.
- Validate the agent's independent searches, comparisons, review evidence,
  citation resolution and handling of contradictory or missing information.
- Update the single mission contract, participant guides, app requests, deck,
  speaker notes and actual screenshots or recordings together after validation.
- Keep public data redistribution, source publication, Workshop Studio
  publication and the excluded human fresh-environment rehearsal as separate
  readiness decisions.
