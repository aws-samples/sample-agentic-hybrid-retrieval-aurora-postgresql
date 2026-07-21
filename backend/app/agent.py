from __future__ import annotations
import asyncio
import logging
import queue
import threading
from typing import Any, Iterator

from .db import get_dict_conn
from .config import get_settings
from .models import AgentAnswerRequest, SearchRequest
from .search import run_hybrid_search

logger = logging.getLogger(__name__)

try:
    from strands import tool
except Exception:  # pragma: no cover - local fallback until deps are installed
    def tool(fn):
        return fn

# Five connected systems (ServiceNow is out of scope for this workshop).
ALL_SYSTEMS = ["slack", "jira", "confluence", "salesforce", "github"]
AGENT_HARNESS = "Strands Agents"
AGENT_TOOLS = [
    "infer_sources",
    "search_evidence",
    "follow_evidence_links",
    "synthesize_cited_answer",
]


def agent_metadata() -> dict[str, Any]:
    settings = get_settings()
    return {
        "harness": AGENT_HARNESS,
        "tools": AGENT_TOOLS,
        "model_provider": "Amazon Bedrock",
        "model_strategy": "configured_roles",
        "model_routing": {
            "planning_and_tool_routing": settings.bedrock_sonnet_model,
            "answer_synthesis": settings.bedrock_opus_model,
        },
        "routing_notes": {
            "planning_and_tool_routing": (
                "Sonnet 5 is the configured role for extended orchestration and "
                "Claude Code; the required canonical replay does not invoke it."
            ),
            "answer_synthesis": (
                "Opus 4.8 runs for live non-canonical synthesis; the required "
                "canonical replay does not invoke it."
            ),
        },
    }


def _infer_sources(question: str) -> list[str]:
    # Lightweight keyword heuristic, not a model call: it only REORDERS the five
    # systems by likely relevance and never drops one, so the priority hint can
    # never cause a system to be missed — the hybrid ranker still sees every
    # source. Deliberately simple so the workshop's retrieval quality is
    # attributable to Aurora ranking, not to a clever pre-filter here.
    q = question.lower()
    if "slack" in q or "decide" in q or "conversation" in q:
        return ["slack", "jira", "confluence", "salesforce", "github"]
    if "incident" in q or "paging" in q or "ops ticket" in q:
        return ["jira", "slack", "salesforce", "confluence", "github"]
    if "customer" in q or "commitment" in q or "salesforce" in q:
        return ["salesforce", "jira", "confluence", "slack", "github"]
    if "pr" in q or "github" in q or "code" in q:
        return ["github", "jira", "confluence", "slack", "salesforce"]
    return ALL_SYSTEMS


@tool
def infer_sources(question: str) -> list[str]:
    """Infer source-system priority for an operational question."""
    return _infer_sources(question)


def search_evidence_impl(
    query: str,
    source_systems: list[str] | None = None,
    project_key: str | None = None,
    account_name: str | None = None,
    component: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    project = project_key if project_key is not None else ("ORION" if "orion" in query.lower() else None)
    sources = source_systems or _infer_sources(query)
    return run_hybrid_search(SearchRequest(
        query=query,
        source_systems=sources,
        project_key=project,
        account_name=account_name,
        component=component,
        limit=limit,
    ))


@tool
def search_evidence(
    query: str,
    source_systems: list[str] | None = None,
    project_key: str | None = None,
    account_name: str | None = None,
    component: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Run Aurora PostgreSQL hybrid search and return ranked evidence rows."""
    return search_evidence_impl(
        query=query,
        source_systems=source_systems,
        project_key=project_key,
        account_name=account_name,
        component=component,
        limit=limit,
    )


def follow_evidence_links_impl(seed_external_ids: list[str], max_depth: int = 3) -> dict[str, Any]:
    from .insights import follow_links

    return follow_links(seed_external_ids, max_depth=max_depth)


@tool
def follow_evidence_links(seed_external_ids: list[str], max_depth: int = 3) -> dict[str, Any]:
    """Walk object_links from retrieved objects to linked evidence across systems.

    Given the external IDs of objects hybrid search already found (e.g. ["ORION-1473"]),
    walk the ops.object_links graph outward up to max_depth hops and return every
    reachable object with the relation path taken. Use this to pull in evidence a
    single search misses — the PR that fixes a ticket, the customer case it impacts,
    the runbook that gates it — so the answer follows the full cross-system chain.
    """
    return follow_evidence_links_impl(seed_external_ids, max_depth=max_depth)


def _norm_question(question: str) -> str:
    return " ".join((question or "").lower().split())


def _canonical_lookup_norm(question: str) -> str:
    norm = _norm_question(question)
    if (
        "orion" in norm
        and (
            "slip" in norm
            or "delay" in norm
            or "delayed" in norm
            or "blocked" in norm
            or "commitment" in norm
            or "customer" in norm
        )
        and "page in prod" not in norm
    ):
        return _norm_question("Why did Orion slip?")
    return norm


def lookup_canonical_answer(question: str) -> dict[str, Any] | None:
    """Return the stored, cited answer for a known question, or None.

    The seed populates ops.agent_answers with the exact Orion narrative the
    mockups show. When a workshop attendee asks that question, we serve the
    stored rows verbatim (answer body, ordered citations, plan, and the run's
    diagnostics metrics) instead of re-synthesizing — so the demo is stable and
    byte-identical to the mockups.
    """
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.run_id, a.question, a.answer, a.confidence,
                           a.source_count, a.system_count, a.citations,
                           to_jsonb(m) AS metrics
                    FROM ops.agent_answers a
                    LEFT JOIN ops.retrieval_run_metrics m ON m.run_id = a.run_id
                    WHERE a.question_norm = %s
                    LIMIT 1
                    """,
                    (_canonical_lookup_norm(question),),
                )
                return cur.fetchone()
    except Exception:
        # Table may not exist yet (schema not migrated) — fall back to synthesis.
        return None


def attach_object_ids(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Resolve each citation's object_id from source_objects so the UI can deep-link.

    The stored citations key on (source_system, external_id); the live results only
    cover the top-k, so a cited object below the cut (e.g. the GitHub PR) would have
    no object_id if we joined against results alone. Resolve straight from the
    canonical source_objects table instead.
    """
    if not citations:
        return citations or []
    pairs = [(c.get("source_system"), c.get("external_id")) for c in citations if c.get("external_id")]
    if not pairs:
        return citations
    systems = [p[0] for p in pairs]
    externals = [p[1] for p in pairs]
    id_by_key: dict[str, str] = {}
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source_system, external_id, object_id
                    FROM ops.source_objects
                    WHERE source_system = ANY(%s) AND external_id = ANY(%s)
                    """,
                    (systems, externals),
                )
                for row in cur.fetchall():
                    id_by_key[f"{row['source_system']}:{row['external_id']}"] = str(row["object_id"])
    except Exception:
        return citations
    return [
        {**c, "object_id": id_by_key.get(f"{c.get('source_system')}:{c.get('external_id')}")}
        for c in citations
    ]


def derive_commitments(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Structured impacted-commitment rows, derived live from cited object metadata.

    The commit table on the Answer page shows real contractual facts (account, ARR,
    contracted go-live date, current status). Those live in the Salesforce object's
    metadata in Aurora — never hard-coded — so we read them from the cited objects
    here. Narrative details (renegotiated date, credits) stay in the answer prose.
    """
    if not citations:
        return []
    object_ids = [c["object_id"] for c in citations if c.get("object_id") and c.get("source_system") == "salesforce"]
    if not object_ids:
        return []
    rows: list[dict[str, Any]] = []
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT object_id, external_id, account_name, status, priority, metadata
                    FROM ops.source_objects
                    WHERE object_id = ANY(%s::uuid[])
                    """,
                    (object_ids,),
                )
                fetched = cur.fetchall()
    except Exception:
        return []
    n_by_object = {c["object_id"]: c.get("n") for c in citations if c.get("object_id")}
    for row in fetched:
        md = row.get("metadata") or {}
        arr = md.get("ARR")
        rows.append(
            {
                "citation_n": n_by_object.get(str(row["object_id"])),
                "account_name": row.get("account_name"),
                "external_id": row["external_id"],
                "subject": md.get("Subject"),
                "arr": arr,
                "arr_label": f"${arr / 1_000_000:.1f}M ARR" if isinstance(arr, (int, float)) else None,
                "contracted_go_live": md.get("ContractGoLive"),
                "status": row.get("status"),
                "priority": row.get("priority"),
            }
        )
    return rows


def _index_citations(results: list[dict[str, Any]]) -> dict[str, int]:
    return {f"{r['source_system']}:{r['external_id']}": i + 1 for i, r in enumerate(results[:8])}


def _citation(row: dict[str, Any] | None, index: dict[str, int]) -> str:
    if not row:
        return ""
    key = f"{row['source_system']}:{row['external_id']}"
    return f"[{index[key]}]" if key in index else ""


def _compact_text(value: Any, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _source_name(row: dict[str, Any]) -> str:
    system = str(row.get("source_system") or "source").replace("_", " ").title()
    source_type = row.get("source_type")
    if source_type:
        return f"{system} {source_type}"
    return system


def _row_summary(row: dict[str, Any], citation_index: dict[str, int]) -> str:
    citation = _citation(row, citation_index)
    source = _source_name(row)
    external_id = row.get("external_id") or "source object"
    title = _compact_text(row.get("title"), 120)
    snippet = _compact_text(row.get("snippet") or title)
    meta_parts = [
        row.get("status"),
        row.get("priority"),
        row.get("owner"),
        row.get("account_name"),
        row.get("component"),
    ]
    meta = " · ".join(str(part) for part in meta_parts if part)
    prefix = f"{source} {external_id}"
    if title:
        prefix = f"{prefix} — {title}"
    if meta:
        prefix = f"{prefix} ({meta})"
    return f"{prefix}: {snippet} {citation}".strip()


def synthesize_answer(question: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return "No ranked evidence was retrieved for this question. Broaden the filters or ingest more source objects before taking action."

    citation_index = _index_citations(results)
    cited_rows = results[: min(6, len(results))]
    leading = _row_summary(cited_rows[0], citation_index)
    supporting = [_row_summary(row, citation_index) for row in cited_rows[1:]]
    answer = f"The highest-ranked evidence is {leading}."
    if supporting:
        answer += " Supporting evidence: " + " ".join(f"{item}." for item in supporting)
    return answer


def synthesize_cited_answer_impl(question: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    citations = [
        {
            "n": i + 1,
            "source_system": r["source_system"],
            "external_id": r["external_id"],
            "title": r["title"],
            "url": r["url"],
        }
        for i, r in enumerate(results[:8])
    ]
    return {
        "answer": synthesize_answer(question, results),
        "citations": citations,
    }


@tool
def synthesize_cited_answer(question: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthesize an extractive cited answer from ranked evidence rows."""
    return synthesize_cited_answer_impl(question, results)


def _canonical_response(req: AgentAnswerRequest, canonical: dict[str, Any]) -> dict[str, Any]:
    """Assemble the verbatim canonical answer from the stored ops.agent_answers row.

    Serves the stored run's persisted candidates as `results` so the demo needs no
    live search or text-model call — it is byte-identical to the mockups and does
    not depend on Bedrock being reachable.
    """
    answer_body = canonical["answer"]
    citations = attach_object_ids(canonical["citations"])
    run_id = str(canonical["run_id"]) if canonical.get("run_id") else None
    return {
        "question": req.question,
        "agent": agent_metadata(),
        "run_id": run_id,
        "canonical": True,
        "confidence": float(canonical["confidence"]),
        "source_count": canonical["source_count"],
        "system_count": canonical["system_count"],
        "answer": answer_body.get("body") if isinstance(answer_body, dict) else answer_body,
        "plan": answer_body.get("plan") if isinstance(answer_body, dict) else None,
        "citations": citations,
        "commitments": derive_commitments(citations),
        "metrics": canonical.get("metrics"),
        "results": persisted_run_results(run_id) if run_id else [],
    }


def persisted_run_results(run_id: str) -> list[dict[str, Any]]:
    """Persisted candidate rows, including their real source passage."""
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.chunk_id, c.object_id, o.source_system, o.source_type,
                           o.external_id, o.title, o.url, o.status, o.priority, o.owner,
                           o.account_name, o.project_key, o.component, o.updated_at,
                           c.text_rank, c.vector_score, c.trigram_score, c.metadata_score,
                           c.recency_score, c.rrf_score, c.rerank_score, c.final_score,
                           c.explanation,
                           left(regexp_replace(ch.chunk_text, '\\s+', ' ', 'g'), 480) AS snippet
                    FROM ops.retrieval_candidates c
                    JOIN ops.source_objects o ON o.object_id = c.object_id
                    LEFT JOIN ops.object_chunks ch ON ch.chunk_id = c.chunk_id
                    WHERE c.run_id = %s
                    ORDER BY
                      CASE WHEN c.rerank_score IS NULL THEN 1 ELSE 0 END,
                      c.rerank_score DESC NULLS LAST,
                      c.final_score DESC NULLS LAST
                    """,
                    (run_id,),
                )
                return cur.fetchall()
    except Exception:
        return []


_LIVE_PLAN = [
    "decompose operational question",
    "search_evidence with inferred source and project filters",
    "collect ranked evidence and persisted diagnostics",
    "synthesize cited answer with Strands agent over Amazon Bedrock",
]
_FALLBACK_PLAN_STEP = "synthesize extractive cited answer from retrieved rows (fallback)"


def _live_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The top-k evidence rows as ordered, object-id-resolved citation records."""
    return attach_object_ids([
        {
            "n": i + 1,
            "source_system": r["source_system"],
            "external_id": r["external_id"],
            "title": r["title"],
            "url": r["url"],
            "object_id": r.get("object_id"),
        }
        for i, r in enumerate(results[:8])
    ])


def _live_answer(req: AgentAnswerRequest, search: dict[str, Any]) -> dict[str, Any]:
    """Non-canonical answer: real Strands+Bedrock synthesis with template fallback."""
    results = search["results"]
    citations = _live_citations(results)
    plan = list(_LIVE_PLAN)
    synthesis_meta: dict[str, Any] = {"mode": "live"}
    try:
        from .synthesis import synthesize_live

        live = synthesize_live(req.question, results)
        answer = live["answer"]
        synthesis_meta.update({"usage": live.get("usage"), "model": live.get("model")})
    except Exception as exc:
        logger.warning("Live synthesis unavailable; using extractive fallback: %s", exc)
        answer = synthesize_answer(req.question, results)
        synthesis_meta = {"mode": "extractive-fallback", "error": str(exc)}
        plan[-1] = _FALLBACK_PLAN_STEP
    return {
        "question": req.question,
        "agent": agent_metadata(),
        "run_id": search["run_id"],
        "canonical": False,
        "plan": plan,
        "answer": answer,
        "synthesis": synthesis_meta,
        "citations": citations,
        "commitments": derive_commitments(citations),
        "results": results,
    }


def _flatten_rich(tokens: Any) -> str:
    """Flatten one rich-token block to plain text — mirrors frontend flattenRich.

    A block is a list of tokens shaped {text}/{b}/{hl}/{cite}. Citation chips carry
    no prose, so they contribute nothing; bold/highlight markers contribute their
    literal text. Kept in lock-step with frontend/src/main.tsx:flattenRich so the
    streamed preview matches what the UI renders.
    """
    if not isinstance(tokens, list):
        return ""
    out: list[str] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        if "text" in token:
            out.append(str(token["text"]))
        elif "b" in token:
            out.append(str(token["b"]))
        elif "hl" in token:
            out.append(str(token["hl"]))
    return "".join(out)


def _answer_body_text(body: Any) -> str:
    """The answer body as one plain-text string in reading order.

    Mirrors frontend/src/main.tsx:answerBodyText: a plain string passes through;
    a structured AnswerBody joins its lead/why/decided/impacted blocks with a
    space. Used to drive the token stream for the canonical (rich-block) answer.
    """
    if not body:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        blocks = [_flatten_rich(body.get(key)) for key in ("lead", "why", "decided", "impacted")]
        return " ".join(block for block in blocks if block)
    return str(body)


def _chunk_text(text: str, size: int = 24) -> Iterator[str]:
    """Split text into fixed-size slices so concatenating the tokens is byte-exact.

    Chunking by character count (not by word) keeps the reassembled preview
    identical to the flattened source, which matters for the canonical answer that
    must stay byte-for-byte the same as the mockups.
    """
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _iter_live_tokens(question: str, results: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Drive synthesis.stream_live (async) from sync code, yielding each event.

    The SSE route is a sync FastAPI endpoint with no running event loop. We consume
    the async generator inside ONE continuous `run_until_complete` on a dedicated
    thread and hand each event across a queue, rather than pumping `__anext__` a
    step at a time. Stepping the loop per item would attach and detach Strands'
    OpenTelemetry span context in different loop contexts, raising "token created
    in a different Context" on every token; a single continuous run keeps the span
    context balanced while still streaming token-by-token through the queue.
    """
    from .synthesis import stream_live

    events: queue.Queue = queue.Queue()
    sentinel = object()

    def _pump() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _consume() -> None:
            async for event in stream_live(question, results):
                events.put(("event", event))

        try:
            loop.run_until_complete(_consume())
        except Exception as exc:  # forwarded to the consumer thread
            events.put(("error", exc))
        finally:
            loop.close()
            events.put(("end", sentinel))

    thread = threading.Thread(target=_pump, name="verity-synthesis", daemon=True)
    thread.start()
    try:
        while True:
            kind, payload = events.get()
            if kind == "event":
                yield payload
            elif kind == "error":
                raise payload
            else:  # end
                break
    finally:
        thread.join()


def _stream_canonical(
    req: AgentAnswerRequest, canonical: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """Stream the stored canonical answer: no Bedrock call, byte-identical output.

    The stored answer body is a structured rich-block object, not a flat string.
    We stream its flattened plain text as `token` events for the typewriter reveal,
    but emit the structured body verbatim in the `done` event so the UI renders the
    same rich, cited answer the non-streaming endpoint returns.
    """
    payload = _canonical_response(req, canonical)
    body = payload.get("answer")
    yield {
        "type": "meta",
        "data": {
            "question": req.question,
            "run_id": payload.get("run_id"),
            "canonical": True,
            "agent": payload.get("agent"),
            "plan": payload.get("plan"),
            "citations": payload.get("citations"),
            "commitments": payload.get("commitments"),
            "confidence": payload.get("confidence"),
            "source_count": payload.get("source_count"),
            "system_count": payload.get("system_count"),
        },
    }
    for chunk in _chunk_text(_answer_body_text(body)):
        yield {"type": "token", "data": {"text": chunk}}
    yield {
        "type": "done",
        "data": {
            "answer": body,
            "canonical": True,
            "synthesis": {"mode": "canonical"},
            "results": payload.get("results"),
        },
    }


def _stream_live(req: AgentAnswerRequest, search: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Stream a live Strands+Bedrock synthesis, falling back to the extractive template."""
    results = search["results"]
    citations = _live_citations(results)
    commitments = derive_commitments(citations)
    plan = list(_LIVE_PLAN)
    yield {
        "type": "meta",
        "data": {
            "question": req.question,
            "run_id": search["run_id"],
            "canonical": False,
            "agent": agent_metadata(),
            "plan": plan,
            "citations": citations,
            "commitments": commitments,
        },
    }
    parts: list[str] = []
    usage = model = stop_reason = None
    streamed = False
    try:
        for event in _iter_live_tokens(req.question, results):
            if event.get("type") == "token":
                text = event.get("text") or ""
                if text:
                    parts.append(text)
                    streamed = True
                    yield {"type": "token", "data": {"text": text}}
            elif event.get("type") == "usage":
                usage = event.get("usage")
                model = event.get("model")
                stop_reason = event.get("stop_reason")
        answer = "".join(parts).strip()
        if not answer:
            raise ValueError("empty synthesis from model")
        synthesis_meta: dict[str, Any] = {
            "mode": "live",
            "usage": usage,
            "model": model,
            "stop_reason": stop_reason,
        }
    except Exception as exc:
        logger.warning("Live streaming synthesis unavailable; using extractive fallback: %s", exc)
        answer = synthesize_answer(req.question, results)
        synthesis_meta = {"mode": "extractive-fallback", "error": str(exc)}
        plan[-1] = _FALLBACK_PLAN_STEP
        if not streamed:
            for chunk in _chunk_text(answer):
                yield {"type": "token", "data": {"text": chunk}}
    yield {
        "type": "done",
        "data": {
            "answer": answer,
            "canonical": False,
            "plan": plan,
            "synthesis": synthesis_meta,
            "citations": citations,
            "commitments": commitments,
            "results": results,
        },
    }


def stream_answer(req: AgentAnswerRequest) -> Iterator[dict[str, Any]]:
    """Stream an agent answer as {'type', 'data'} events, canonical-first.

    Yields a `meta` event, then `token` events carrying incremental text, then a
    terminal `done` event with the full answer, citations, commitments, and token
    usage. The canonical Orion question streams its stored answer with no Bedrock
    call; any other question runs a live hybrid search and streams a real
    Strands+Bedrock synthesis, falling back to the extractive template on failure.
    """
    canonical = lookup_canonical_answer(req.question)
    if canonical:
        yield from _stream_canonical(req, canonical)
        return
    search = search_evidence_impl(
        query=req.question,
        source_systems=req.source_systems,
        project_key=req.project_key,
        account_name=req.account_name,
        component=req.component,
        limit=req.limit,
    )
    yield from _stream_live(req, search)


def answer_question(req: AgentAnswerRequest) -> dict[str, Any]:
    """Answer an operational question, canonical-first.

    Checks ops.agent_answers BEFORE embedding or searching: the flagship Orion
    question is served verbatim without spending a Bedrock embedding call or a
    text-model call. Any other question runs a real hybrid search and then a live
    Strands+Bedrock synthesis (falling back to an extractive template if Bedrock
    is unreachable).
    """
    canonical = lookup_canonical_answer(req.question)
    if canonical:
        return _canonical_response(req, canonical)

    search = search_evidence_impl(
        query=req.question,
        source_systems=req.source_systems,
        project_key=req.project_key,
        account_name=req.account_name,
        component=req.component,
        limit=req.limit,
    )
    return _live_answer(req, search)
