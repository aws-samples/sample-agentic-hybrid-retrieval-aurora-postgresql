# Session & Memory

The third Playground tab teaches the two parts of AgentCore Memory: conversation
events stored by actor and session, and long-term records produced by strategies.
It keeps Alex's home office as the context while making AgentCore's behavior
inspectable. There is no budget exercise or manually entered preference form.

Optional Lab 4 asks **Can Mosaic remember Alex’s preferences across
conversations?** Its question, message, requests and checkpoints live in
`data/evals/mosaic_labs_missions.json` under `optional_labs.memory`. It is outside
the required hour; extraction has no guaranteed duration. The page begins with
Preferences selected and the contract's monitor example in **Alex says**.
The **Original question** and **Change Alex’s request** actions fill the composer;
neither sends a model request until **Ask Mosaic** is selected.

Ask Mosaic in Shop uses this same connection through **Use saved memories**,
which starts off. Each opted-in answer has a **Memories used** section containing
the records actually read, the number of earlier conversation events read, and
whether saving the conversation succeeded. **View memories** opens the Playground
inspector. Clearing chat starts a new session, keeping the same browser actor
and saved facts and preferences. Follow-ups work from the current shortlist with
memory off. Required lab requests keep memory off and do not offer this control.

## What the page shows

The page uses **Facts**, **Preferences**, **Summaries**, and **Past outcomes**.
**Save message** writes a conversation event; **Find relevant memories** searches
saved facts and preferences. Technical configuration stays under **AWS settings
and documentation**. Structured records show a source-supplied preview when
available, with the complete original retained under **Record details**.
The table below maps the interface to the AgentCore API types.

| AgentCore strategy | What it keeps | Mosaic scope |
|---|---|---|
| Semantic | Facts from conversation, such as Alex sharing an office | Across this actor's sessions |
| User preference | Choices and preferences extracted from conversation | Across this actor's sessions |
| Session summary | Topics and decisions within a conversation | One session |
| Episodic | Completed interactions and outcomes, with reflections across episodes | Episodes per session; reflections per actor |

The strategy status and configuration come from GetMemory. Events come from
ListEvents. The record inspector uses ListMemoryRecords; Recall uses
RetrieveMemoryRecords for relevant semantic and user-preference records.
The answer area starts empty. Only a request submitted on this visit appears
inline; saved turns remain available in the collapsed **Earlier answers** section.
Switching sessions or adding another event clears the current answer display.
**New session** keeps the same Alex and his extracted memories. **Start fresh**
begins with a separate Alex in this browser and clears the visible conversation,
records, recalled context and answer. Earlier sessions and memory records remain
stored; the reset does not delete anything from the shared AgentCore resource.
Examples fill the editable message field and select the matching strategy. They become real events when the
visitor submits them; the application never fabricates extracted records.

Runs started from the Playground and the lab proofs keep memory off, so their
sessions appear in the list with no conversation events, and the page says so.
Facts and preferences are kept for the actor across sessions, and every record
names its scope, so a record can appear under a session that stored no event.

Extraction runs asynchronously. A stored event does not prove that extraction
finished, and an empty record list is not a failure or a promise of a future
record. Episodic extraction waits for a completed episode. The UI reports actual
records and access errors separately, with a refresh action.

## Enable it

Apply `db/sql/10_agent_audit.sql` to the existing Aurora database. Fresh installs
already apply it. The additive `mosaic.shopper_profile` table connects a browser
actor to its active Aurora session.

```bash
uv run python scripts/setup_session_memory.py --region us-east-1 --create --configure-strategies
```

The script creates a dedicated resource or adds missing Mosaic strategies to the
uniquely named existing resource. It waits for the resource and all strategies
to be active. It does not delete existing strategies. Set
`MOSAIC_AGENTCORE_MEMORY_ID` to its returned ID and restart the API.

All four are built-in strategies. Overrides and self-managed strategies remain
available extension paths described in the page's final disclosure; they are not
silently configured. Runtime and Gateway are separate services and deployments.

The API role needs `bedrock-agentcore:GetMemory`, `bedrock-agentcore:CreateEvent`,
`bedrock-agentcore:ListEvents`, `bedrock-agentcore:ListMemoryRecords`, and
`bedrock-agentcore:RetrieveMemoryRecords` on the dedicated memory ARN. Provisioning
requires ListMemories, CreateMemory and UpdateMemory separately. Memory is
optional for the three required retrieval labs.

## Context and evidence

Same-session Ask requests read recent conversation events and can resume the
prior Aurora shortlist. A new session starts with no previous events or
shortlist; facts and preferences remain retrievable under the same actor.
The prompt receives bounded memory text as untrusted context, with the current
message taking priority. Application code does not turn memory into price or
stock filters. Product eligibility, retrieval and citation validation stay on
their normal production paths.

Each opted-in completed turn writes its actual USER and ASSISTANT messages as an
AgentCore event. The Aurora turn records the memory record IDs and text used,
event IDs read, and the event-write outcome. A failed write remains visible and
does not discard the cited answer. A memory read error stops an opted-in request;
retry or turn memory off. Neither records nor events enter product citation scope.

## Identity and retention

The demo uses a random 256-bit HttpOnly, SameSite cookie and hashes it into the
actor ID. Session ownership is checked before reading events or running a model.
That includes follow-ups naming a prior run, even when the cookie is omitted.
Callers cannot submit actor IDs or namespace paths. Configured namespaces must
start with `/mosaic/{actorId}/`; shared paths are excluded. Reflections remain
scoped to the actor rather than combining different shoppers.

This is a browser capability, not a production account login. Clearing browser
data loses access to that browser's history. Bind actors to authenticated users
before serving real customers. The resource's 30-day event retention does not
expire long-term records. Account-wide deletion controls remain separate work;
the tab does not promise that starting a session deletes prior memories.

The UI reads the latest 12 Aurora sessions and 20 turns per session; event and
record reads are bounded and show when more data exists. No history or memories
are copied to localStorage. Previous anonymous runs remain unassigned.

## Verification and references

The 20 September rehearsal verified actual event storage and preference
extraction, same-actor recall in a new session with zero prior conversation
events, a fresh Aurora search and cited product specifications, explicit request
precedence, and a separate actor receiving no records and HTTP 404 for the
original session. Memory-off requests read zero events and zero records. The
current catalog supplies these product proofs; this is not acceptance of the
staged public-catalog replacement. See the [rehearsal evidence](evidence/workshop-rehearsal-2026-09-20.md).

A live check on 9 September stored an Alex workspace message, then read actual
semantic facts, user preferences and a session summary. A new session recalled
relevant records without the old session's events and produced a cited answer
with a new AgentCore event. Episodic was active but returned no completed episode
at that check; the page showed that empty state. These are functional checks,
not extraction latency benchmarks or room-capacity measurements.

See AWS's [strategy overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html),
[built-in configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-configuring-built-in-strategies.html),
and [episodic behavior](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/episodic-memory-strategy.html).
