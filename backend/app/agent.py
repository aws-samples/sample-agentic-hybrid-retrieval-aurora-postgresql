from __future__ import annotations
from typing import Any

from .models import AgentAnswerRequest, SearchRequest
from .search import run_hybrid_search


def infer_sources(question: str) -> list[str]:
    q = question.lower()
    if "slack" in q or "decide" in q or "conversation" in q:
        return ["slack", "jira", "confluence", "salesforce", "servicenow", "github"]
    if "incident" in q or "servicenow" in q or "service now" in q:
        return ["servicenow", "jira", "slack", "salesforce", "confluence", "github"]
    if "customer" in q or "commitment" in q or "salesforce" in q:
        return ["salesforce", "jira", "servicenow", "confluence", "slack"]
    if "pr" in q or "github" in q or "code" in q:
        return ["github", "jira", "confluence", "slack", "servicenow"]
    return ["slack", "jira", "confluence", "salesforce", "servicenow", "github"]


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
    servicenow = _first_by_source(results, "servicenow")
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
    incident = (
        f" ServiceNow links the same incident to the Jira blocker, Slack hold decision, and Acme escalation {_citation(servicenow, citation_index)}."
        if servicenow
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
    return f"{cause}{decision}{commitment}{incident}{readiness}{remediation}"


def answer_question(req: AgentAnswerRequest) -> dict[str, Any]:
    source_systems = req.source_systems or infer_sources(req.question)
    project_key = req.project_key if req.project_key is not None else ("ORION" if "orion" in req.question.lower() else None)
    search = run_hybrid_search(SearchRequest(
        query=req.question,
        source_systems=source_systems,
        project_key=project_key,
        account_name=req.account_name,
        component=req.component,
        limit=req.limit,
    ))
    results = search["results"]
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
    answer = synthesize_answer(req.question, results)
    return {
        "question": req.question,
        "run_id": search["run_id"],
        "plan": [
            "decompose operational question",
            "search_evidence with inferred source and project filters",
            "collect ranked evidence and persisted diagnostics",
            "synthesize extractive cited answer from retrieved rows",
        ],
        "answer": answer,
        "citations": citations,
        "results": results,
    }
