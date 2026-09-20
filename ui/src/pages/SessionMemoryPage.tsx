import { memoryRecordText } from "../memoryRecordText";
import { ArrowRight, LoaderCircle, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Markdown from "react-markdown";
import { Link } from "wouter";
import { api } from "../api";
import { ProductAnswer } from "../components/ProductAnswer";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicRunButton } from "../components/MosaicRunButton";
import { playgroundQueryHref } from "../navigation";
import type { MemoryEvent, MemoryRecord, SessionMemoryResponse, ShopperSession } from "../types";
import "../inspector.css";
import "../session-memory.css";

const strategies = [
  { type: "SEMANTIC", name: "Facts", technical: "About Alex", title: "What Alex has told us.", description: "Keeps useful facts from the conversation, such as the equipment Alex already owns and how he works.", scope: "Across Alex’s sessions", process: "Identify useful details → update saved records", detail: "New facts can be added to existing records as the conversation changes.", example: "I’m setting up my home office. I already have a desk and laptop, and I take video calls most days.", source: "semantic-memory-strategy.html" },
  { type: "USER_PREFERENCE", name: "Preferences", technical: "Likes and dislikes", title: "What Alex tends to prefer.", description: "Keeps the choices Alex describes, such as quiet equipment and a warm, uncluttered desk.", scope: "Across Alex’s sessions", process: "Identify useful details → update saved records", detail: "A preference is learned from conversation; it is not a setting entered into a form.", example: "I prefer quiet keyboards and a warm, uncluttered desk. I don’t like bright lights on my equipment.", source: "user-preference-memory-strategy.html" },
  { type: "SUMMARIZATION", name: "Summaries", technical: "Conversation recap", title: "Where the conversation got to.", description: "Condenses the topics and decisions within one session so an agent can pick up a longer conversation.", scope: "This session", process: "Update the conversation summary", detail: "One session can have several summary records. A new session has its own summary.", example: "We’ve settled on making calls clearer first, then finding a quiet keyboard. The chair can wait until I’ve measured the desk.", source: "summary-strategy.html" },
  { type: "EPISODIC", name: "Past outcomes", technical: "What worked", title: "What happened, and what worked.", description: "Keeps what Alex tried and how it turned out. AgentCore can compare past outcomes to find what worked.", scope: "Outcomes from this session · lessons from Alex’s earlier sessions", process: "Identify the outcome → update records → learn from past results", detail: "AgentCore saves an outcome after it detects that an interaction is complete. A single message may not produce one.", example: "My old keyboard was audible on calls. I compared quieter options, chose one after checking the reviews, and my colleagues can no longer hear the typing. That solved it.", source: "episodic-memory-strategy.html" },
];
const date = (value: string) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));


function Records({ records, sessionId = null }: { records: MemoryRecord[]; sessionId?: string | null }) {
  return <div className="memory-records">{records.map((record) => <article key={record.id} className="memory-record">
    <div className="memory-record-meta"><span>Saved memory</span><span className="memory-record-scope">{sessionId && record.namespaces.some((path) => path.includes(sessionId)) ? "From this session" : "Kept for Alex across sessions"}</span>{record.created_at && <time dateTime={record.created_at}>{date(record.created_at)}</time>}</div>
    <p className="memory-record-text">{memoryRecordText(record.text)}</p>
    <details><summary>Record details</summary><dl><dt>Record ID</dt><dd><code>{record.id}</code></dd><dt>Memory configuration ID</dt><dd><code>{record.strategy_id}</code></dd><dt>Namespace · where it is stored</dt><dd>{record.namespaces.map((path) => <code key={path}>{path}</code>)}</dd></dl><pre>{record.text}</pre></details>
  </article>)}</div>;
}

function Turn({ turn }: { turn: ShopperSession["turns"][number] }) {
  return <article className="memory-turn"><h3>{turn.question}</h3>
    <p className="memory-turn-meta">{turn.memory.records?.length ?? 0} long-term memories read · {turn.memory.event_ids_read?.length ?? 0} conversation events read</p>
    {turn.memory.write_status === "failed" && <p role="alert">The answer is saved in Aurora, but its AgentCore event could not be stored.</p>}
    {turn.answer ? <div className="memory-answer-copy"><ProductAnswer text={turn.answer} products={turn.products} citations={turn.citations} /></div> : <p>This run has no completed answer.</p>}
    <details className="memory-sources"><summary>Memories, searches and sources used</summary>
      {turn.memory.records?.length ? <Records records={turn.memory.records} /> : <p>No long-term memory was added to this request.</p>}
      <div className="memory-search-links">{turn.search_ids.map((id, i) => <Link key={id} href={playgroundQueryHref(turn.question, {}, id)}>Search {i + 1}<ArrowRight size={14} aria-hidden="true" /></Link>)}</div>
      {turn.citations.map((citation) => <p key={`${citation.number}-${citation.evidence_id}`}>[{citation.number}] {citation.title} — {citation.quote}</p>)}
    </details>
  </article>;
}

export function SessionMemoryPage() {
  const [data, setData] = useState<SessionMemoryResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [type, setType] = useState("SEMANTIC");
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [eventsMore, setEventsMore] = useState(false);
  const [text, setText] = useState(strategies[0].example);
  const [question, setQuestion] = useState("Which headphones would suit the way I work at home?");
  const [recalled, setRecalled] = useState<MemoryRecord[] | null>(null);
  const [useMemory, setUseMemory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [stage, setStage] = useState("");
  const [answer, setAnswer] = useState("");
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const mounted = useRef(true);
  const refreshSequence = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const strategy = strategies.find((item) => item.type === type)!;
  const configured = data?.configuration?.strategies.find((item) => item.type === type);
  const session = data?.sessions.find((item) => item.agent_session_id === selected);
  const currentTurn = session?.turns.find((turn) => turn.run_id === currentRunId);
  const earlierTurns = session?.turns.filter((turn) => turn.run_id !== currentRunId) ?? [];
  // Playground and lab runs keep memory off on purpose, so their sessions hold no
  // events; saying so is the difference between a design and an outage.
  const memoryOff = Boolean(session?.turns.length) && Boolean(session?.turns.every((turn) => turn.memory?.status !== "connected"));
  const connected = data?.memory_status === "connected" && data.configuration?.status === "ACTIVE";

  const refresh = useCallback(async (selectActive = false) => {
    const sequence = ++refreshSequence.current;
    const next = await api.sessionMemory();
    if (mounted.current && sequence === refreshSequence.current) { setData(next); if (selectActive) setSelected(next.active_session_id); setRevision((n) => n + 1); }
    return next;
  }, []);
  useEffect(() => {
    mounted.current = true;
    refresh(true).catch((cause) => { if (mounted.current) setError(cause.message); });
    return () => { mounted.current = false; abort.current?.abort(); };
  }, [refresh]);
  useEffect(() => {
    let current = true;
    setRecords([]); setEvents([]); setReadError(""); setHasMore(false); setEventsMore(false);
    if (!connected) return;
    setLoading(true);
    Promise.all([
      selected ? api.memoryEvents(selected) : Promise.resolve({ events: [], has_more: false }),
      configured ? api.memoryRecords(configured.id, selected ?? undefined) : Promise.resolve({ records: [], has_more: false }),
    ]).then(([eventResult, memoryResult]) => {
      if (current) { setEvents(eventResult.events); setEventsMore(eventResult.has_more); setRecords(memoryResult.records); setHasMore(memoryResult.has_more); }
    }).catch((cause) => { if (current) setReadError(cause.message); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [selected, configured?.id, connected, revision]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : "That did not finish. Retry."); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function add(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      const result = await api.addMemoryEvent(text, selected ?? undefined);
      if (!mounted.current) return;
      setSelected(result.session_id); setRecalled(null); setCurrentRunId(null); setAnswer("");
      await refresh(); setNotice("Message saved in AgentCore. It processes useful details in the background; refresh to see any new memories.");
    });
  }
  async function startNew() {
    await act(async () => { await api.newSession(); if (!mounted.current) return; setSelected(null); setAnswer(""); setCurrentRunId(null); setRecalled(null); await refresh(); setNotice("New session. Alex keeps the same user ID, so his earlier memories remain available."); });
  }
  async function resetAlex() {
    await act(async () => {
      await api.resetAlex();
      if (!mounted.current) return;
      setData(null); setSelected(null); setAnswer(""); setCurrentRunId(null); setRecalled(null);
      setEvents([]); setRecords([]); setReadError(""); setHasMore(false); setEventsMore(false);
      setType("SEMANTIC"); setText(strategies[0].example);
      setQuestion("Which headphones would suit the way I work at home?"); setUseMemory(true);
      await refresh(true);
      if (mounted.current) setNotice("A fresh start for Alex. Add a message, then check what AgentCore remembers. Earlier records have not been deleted.");
    });
  }
  async function ask(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(""); setAnswer(""); setCurrentRunId(null); setStage(useMemory ? "Reading memories" : "Reading the request");
    const controller = new AbortController(); abort.current = controller;
    try {
      await api.agentStream(question, {}, (event) => {
        if (!mounted.current) return;
        if (event.type === "stage") setStage(({ understand: "Reading the request", retrieve: "Finding products", rank: "Comparing matches", answer: "Preparing the answer" })[event.id]);
        else if (event.type === "answer_delta") setAnswer((value) => value + event.delta);
        else if (event.type === "complete") { setAnswer(event.response.answer); setCurrentRunId(event.response.agent_run_id); }
      }, undefined, { signal: controller.signal, sessionId: selected ?? undefined, useMemory });
      const next = await refresh(); if (mounted.current) { setSelected(next.active_session_id); setAnswer(""); }
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : "The request did not finish. Retry."); }
    finally { if (mounted.current) { setPending(false); setStage(""); } }
  }
  const locked = busy || pending;
  return <div className="page pipeline-inspector session-memory">
    <MosaicLabsTabs active="memory" />
    <div className="inspector-intro"><MosaicLabsMasthead title="What stays with Alex." deck="AgentCore Memory saves the conversation and keeps useful facts, preferences, summaries and past outcomes for later requests." supportingText="Optional after the three labs. Playground runs and lab checks keep memory off; you can complete Retrieve, Rank and Reason without this connection." /></div>
    <ol className="memory-flow" aria-label="How AgentCore Memory works"><li><span>01 · Short-term</span><strong>Save the conversation</strong><p>Messages grouped by user and conversation.</p></li><li><span>02 · Remember</span><strong>Keep useful details</strong><p>Choose facts, preferences, summaries or past outcomes.</p></li><li><span>03 · Long-term</span><strong>Use relevant memories</strong><p>Find saved details that help answer the next request.</p></li></ol>
    {error && <div className="memory-error" role="alert"><p>{error}</p>{!data && <button className="secondary-button" onClick={() => { setError(""); refresh(true).catch((cause) => setError(cause.message)); }}>Retry</button>}</div>}
    {!data ? (error ? null : <p className="memory-loading" role="status"><LoaderCircle className="memory-spinner" size={18} />Loading conversations and memory settings…</p>) : <>
      <div className="memory-profile"><img src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="Alex" width={64} height={64} /><div><strong>Same Alex. Many conversations.</strong><span>{connected ? "Connected to AgentCore Memory" : data.memory_status === "unavailable" ? "AgentCore Memory is temporarily unavailable" : "AgentCore Memory is not connected"}</span></div><div className="memory-session-actions"><button className="secondary-button" onClick={startNew} disabled={locked}><Plus size={16} aria-hidden="true" />New session</button><button className="memory-text-button" onClick={resetAlex} disabled={locked}><RotateCcw size={16} aria-hidden="true" />Start fresh</button><small>New session keeps Alex’s memories. Start fresh begins with a new Alex.</small></div></div>
      <div className="memory-session-bar"><label>Session<select value={selected ?? ""} disabled={locked} onChange={(event) => { setSelected(event.target.value || null); setRecalled(null); setAnswer(""); setCurrentRunId(null); }}><option value="">New conversation</option>{data.sessions.map((item) => <option key={item.agent_session_id} value={item.agent_session_id}>{date(item.started_at)} · {item.label || item.turns[0]?.question.slice(0, 70) || "Conversation"}</option>)}</select></label><button className="memory-text-button" onClick={() => act(async () => { await refresh(); })} disabled={locked || loading}><RotateCcw size={16} aria-hidden="true" />Refresh memories</button></div>
      <p className="memory-notice" role="status">{notice}</p>
      <div className="memory-layout">
        <section className="memory-events" aria-labelledby="memory-events-heading"><div className="memory-section-heading"><h2 id="memory-events-heading">The conversation</h2><span className="memory-small-label">Short-term memory</span></div><p className="memory-lead">AgentCore saves the message first, then processes useful details in the background. You can inspect both records separately.</p>
          <form className="memory-event-form" onSubmit={add}><label htmlFor="memory-event-text">Alex says</label><textarea id="memory-event-text" value={text} onChange={(event) => setText(event.target.value)} minLength={4} maxLength={2000} rows={4} required disabled={locked} /><div className="memory-suggestions">{strategies.map((item) => <button type="button" key={item.type} disabled={locked} onClick={() => setText(item.example)}>{item.name} example</button>)}</div><button className="primary-button" disabled={locked || !connected} type="submit"><Plus size={16} aria-hidden="true" />Save message</button></form>
          <div className="memory-event-list">{events.map((event) => <details key={event.id} className="memory-event"><summary><span>{date(event.created_at)}</span><span>{event.messages.length} message{event.messages.length === 1 ? "" : "s"}</span><span className="memory-event-preview">{event.messages[0]?.text}</span></summary>{event.messages.map((message, index) => <div key={index}><span className="memory-small-label">{message.role === "USER" ? "Alex" : message.role === "ASSISTANT" ? "Mosaic" : message.role}</span><p>{message.text}</p></div>)}<code>{event.id}</code></details>)}{!events.length && !loading && !readError && <p className="memory-empty">{selected ? (memoryOff ? "Memory was off for these requests, so their messages were not saved in AgentCore. Alex’s memories from earlier sessions are still shown on the right." : "No saved messages were returned for this session.") : "A new session starts with no saved messages."}</p>}{eventsMore && <p className="memory-empty">Showing 30 saved message groups from this session.</p>}</div>
        </section>
        <section className="memory-strategies" aria-labelledby="memory-strategies-heading"><div className="memory-section-heading"><h2 id="memory-strategies-heading">What AgentCore remembers</h2><span className="memory-small-label">Long-term memory</span></div>
          <div className="memory-strategy-picker" role="group" aria-label="Types of memory">{strategies.map((item) => <button key={item.type} type="button" aria-pressed={type === item.type} onClick={() => setType(item.type)}><span>{item.name}</span><small>{item.technical}</small></button>)}</div>
          <div className="memory-strategy-description"><span className="memory-strategy-status">{configured ? `${configured.status === "ACTIVE" ? "Active" : configured.status.toLowerCase()} in this connection` : "Available in AgentCore · not configured here"}</span><h3>{strategy.title}</h3><p>{strategy.description}</p><dl><dt>Where it is used</dt><dd>{strategy.scope}</dd><dt>Steps</dt><dd>{strategy.process}</dd></dl><p className="memory-strategy-detail">{strategy.detail}</p></div>
          {loading && <p className="memory-loading" role="status"><LoaderCircle className="memory-spinner" size={18} aria-hidden="true" />Reading AgentCore records…</p>}
          {readError && <p className="memory-error" role="alert">{readError}</p>}
          {!loading && !readError && (records.length ? <Records records={records} sessionId={selected} /> : <div className="memory-record-empty"><strong>No records returned yet.</strong><p>{!configured ? "This type of memory is not configured on this connection." : type === "SUMMARIZATION" && !selected ? "Select a session to read its summaries." : "AgentCore processes messages in the background. Saved memories may appear later, and not every message creates one."}</p></div>)}
          {hasMore && <p className="memory-empty">Showing up to 20 records from each storage path.</p>}
          <details className="memory-configuration"><summary>AWS settings and documentation</summary><p>AgentCore groups memory records under a storage path called a namespace. Mosaic uses Alex’s user ID as the actorId, which keeps his records separate from other users.</p>{configured && <pre>{JSON.stringify(configured, null, 2)}</pre>}<a href={`https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/${strategy.source}`} target="_blank" rel="noreferrer">Read the AWS guide for {strategy.name.toLowerCase()}</a></details>
        </section>
      </div>
      <section className="memory-recall" aria-labelledby="memory-recall-heading"><div className="memory-recall-intro"><h2 id="memory-recall-heading">Use saved details in the next request.</h2><p>Find relevant facts and preferences in AgentCore, then ask Mosaic a question. It uses those details to guide the request and searches Aurora for products and supporting sources.</p><details><summary>User, session and memory settings</summary><dl><dt>User ID · this browser’s Alex (actorId)</dt><dd><code>{data.actor_id}</code></dd><dt>Session · this conversation</dt><dd><code>{selected ?? "Created when you save a message or ask Mosaic"}</code></dd><dt>AgentCore Memory resource</dt><dd><code>{data.configuration?.memory_id ?? "Not connected"}</code></dd></dl><p>Saved messages expire after {data.configuration?.event_expiry_days ?? "the configured number of"} days. That setting does not delete long-term memory records.</p></details></div>
        <div><form onSubmit={ask} className="memory-composer"><label htmlFor="memory-question">Ask about Alex’s workspace</label><textarea id="memory-question" value={question} onChange={(event) => { setQuestion(event.target.value); setRecalled(null); }} minLength={4} maxLength={2000} rows={3} required disabled={locked} /><label className="memory-check"><input type="checkbox" checked={useMemory} onChange={(event) => setUseMemory(event.target.checked)} disabled={locked} />Use AgentCore Memory for this request</label><div className="memory-recall-actions"><button type="button" className="secondary-button" disabled={locked || !connected || question.length < 4} onClick={() => act(async () => { const result = await api.recallMemory(question); if (mounted.current) setRecalled(result.records); })}>Find relevant memories</button><MosaicRunButton type="submit" label={pending ? stage || "Reading the request" : "Ask Mosaic"} showLabel running={pending} disabled={locked || (useMemory && data.memory_status === "unavailable")} /></div><p className="memory-empty">{useMemory ? "Reads relevant memories and saves this conversation. Product claims must still cite records from Aurora." : "This request uses Aurora without reading or writing AgentCore Memory."}</p></form>
          {recalled !== null && <div className="memory-recall-results" aria-live="polite"><h3>{recalled.length} relevant memor{recalled.length === 1 ? "y" : "ies"} returned</h3><Records records={recalled} />{!recalled.length && <p>No saved facts or preferences matched this request.</p>}</div>}
          {pending && <p className="memory-progress" role="status"><LoaderCircle className="memory-spinner" size={18} aria-hidden="true" />{stage}</p>}{answer && !currentTurn && <div className="memory-answer-copy"><Markdown>{answer}</Markdown></div>}
          {currentTurn && <div className="memory-current-answer"><Turn turn={currentTurn} /></div>}
          {!pending && !answer && !currentTurn && <p className="memory-empty">Your answer will appear here after you ask Mosaic.</p>}
          {earlierTurns.length > 0 && <details key={selected} className="memory-history"><summary>Earlier answers · {earlierTurns.length}</summary>{earlierTurns.map((turn) => <Turn key={turn.run_id} turn={turn} />)}</details>}
        </div>
      </section>
      <details className="memory-beyond"><summary>Change how memories are created</summary><div><p><strong>Customize the built-in options.</strong> Change the instructions for finding useful details and updating saved records, or choose a different Bedrock model. AgentCore runs the process.</p><p><strong>Run your own process.</strong> Decide what to remember and write records through the memory APIs. Mosaic uses the four built-in options shown above; this is an extension you can build.</p><p><strong>Runtime and Gateway.</strong> Runtime hosts an agent; Gateway connects tools. They are separate from this Memory connection.</p><a href="https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html" target="_blank" rel="noreferrer">Read about AgentCore memory options</a></div></details>
    </>}
  </div>;
}
