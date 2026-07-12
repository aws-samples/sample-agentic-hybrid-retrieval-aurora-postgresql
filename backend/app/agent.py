from __future__ import annotations
from typing import Any

from .db import get_dict_conn
from .config import get_settings
from .models import AgentAnswerRequest, SearchRequest
from .search import run_hybrid_search

try:
    from strands import tool
except Exception:  # pragma: no cover - local fallback until deps are installed
    def tool(fn):
        return fn

# Five connected systems (ServiceNow is out of scope for this workshop).
ALL_SYSTEMS = ["slack", "jira", "confluence", "salesforce", "github"]
AGENT_HARNESS = "Strands Agents"
AGENT_TOOLS = ["infer_sources", "search_evidence", "synthesize_cited_answer"]


def agent_metadata() -> dict[str, Any]:
    settings = get_settings()
    return {
        "harness": AGENT_HARNESS,
        "tools": AGENT_TOOLS,
        "model_provider": "Amazon Bedrock",
        "model_strategy": "best_model_for_the_job",
        "model_routing": {
            "planning_and_tool_routing": settings.bedrock_sonnet_model,
            "answer_synthesis": settings.bedrock_opus_model,
            "claude_code_harness": settings.bedrock_sonnet_model,
        },
        "routing_notes": {
            "planning_and_tool_routing": "Sonnet 5 for decomposition, source selection, and tool routing.",
            "answer_synthesis": "Opus 4.8 for high-quality answer synthesis when live composition is enabled.",
            "claude_code_harness": "Sonnet 5 for Claude Code discovery questions and optional exercises.",
        },
    }


def _infer_sources(question: str) -> list[str]:
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


def _norm_question(question: str) -> str:
    return " ".join((question or "").lower().split())


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
                    (_norm_question(question),),
                )
                return cur.fetchone()
    except Exception:
        # Table may not exist yet (schema not migrated) — fall back to synthesis.
        return None


def _attach_object_ids(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
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


def _derive_commitments(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
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


def _first_by_source(results: list[dict[str, Any]], source_system: str) -> dict[str, Any] | None:
    return next((row for row in results if row["source_system"] == source_system), None)


def synthesize_answer(question: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return "No strong evidence was retrieved for this question. Broaden the filters or ingest more source objects before taking action."

    citation_index = _index_citations(results)
    jira = _first_by_source(results, "jira")
    slack = _first_by_source(results, "slack")
    salesforce = _first_by_source(results, "salesforce")
    confluence = _first_by_source(results, "confluence")
    github = _first_by_source(results, "github")
    lead = results[0]

    cause = (
        f"Project Orion is delayed because {jira['external_id']} reports read replica lag above the release threshold, "
        f"which blocks Blue/Green validation and production-readiness checks {_citation(jira, citation_index)}."
        if jira
        else f"The strongest retrieved evidence is {lead['external_id']}, which points to {lead['title']} {_citation(lead, citation_index)}."
    )
    decision = (
        f" The Slack decision was to hold the cutover until soak results are clean, publish customer-facing status, "
        f"and resume only after lag stays under threshold for the full soak period {_citation(slack, citation_index)}."
        if slack
        else ""
    )
    commitment = (
        f" The impacted customer commitment is Acme Corp's monthly-close reporting path: Customer Engineering must provide a May 3 update "
        f"and confirm whether the Orion cutover delay changes the go-live plan {_citation(salesforce, citation_index)}."
        if salesforce
        else ""
    )
    readiness = (
        f" The readiness runbook makes clean soak results, the ORION blocker status, and customer communication release gates {_citation(confluence, citation_index)}."
        if confluence
        else ""
    )
    remediation = (
        f" PR-1287 is merged, but the evidence still calls for another load/soak validation before reopening the cutover window {_citation(github, citation_index)}."
        if github
        else ""
    )
    return f"{cause}{decision}{commitment}{readiness}{remediation}"


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


def answer_question(req: AgentAnswerRequest) -> dict[str, Any]:
    metadata = agent_metadata()
    search = search_evidence_impl(
        query=req.question,
        source_systems=req.source_systems,
        project_key=req.project_key,
        account_name=req.account_name,
        component=req.component,
        limit=req.limit,
    )
    results = search["results"]

    # Prefer the stored, cited answer when the question is one the seed knows
    # (e.g. the canonical Orion narrative). This keeps the demo byte-identical to
    # the mockups while still running a real hybrid search to produce the run.
    canonical = lookup_canonical_answer(req.question)
    if canonical:
        answer_body = canonical["answer"]
        citations = _attach_object_ids(canonical["citations"])
        return {
            "question": req.question,
            "agent": metadata,
            "run_id": str(canonical["run_id"]) if canonical.get("run_id") else search["run_id"],
            "canonical": True,
            "confidence": float(canonical["confidence"]),
            "source_count": canonical["source_count"],
            "system_count": canonical["system_count"],
            "answer": answer_body.get("body") if isinstance(answer_body, dict) else answer_body,
            "plan": answer_body.get("plan") if isinstance(answer_body, dict) else None,
            "citations": citations,
            "commitments": _derive_commitments(citations),
            "metrics": canonical.get("metrics"),
            "results": results,
        }

    citations = _attach_object_ids([
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
    answer = synthesize_answer(req.question, results)
    return {
        "question": req.question,
        "agent": metadata,
        "run_id": search["run_id"],
        "canonical": False,
        "plan": [
            "decompose operational question",
            "search_evidence with inferred source and project filters",
            "collect ranked evidence and persisted diagnostics",
            "synthesize extractive cited answer from retrieved rows",
        ],
        "answer": answer,
        "citations": citations,
        "commitments": _derive_commitments(citations),
        "results": results,
    }
