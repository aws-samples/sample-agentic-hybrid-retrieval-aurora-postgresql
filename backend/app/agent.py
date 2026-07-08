from __future__ import annotations
from typing import Any

from .models import AgentAnswerRequest, SearchRequest
from .search import run_hybrid_search


def infer_sources(question: str) -> list[str]:
    q = question.lower()
    if "slack" in q or "decide" in q or "conversation" in q:
        return ["slack", "jira", "confluence", "salesforce", "github"]
    if "customer" in q or "commitment" in q or "salesforce" in q:
        return ["salesforce", "jira", "confluence", "slack"]
    if "pr" in q or "github" in q or "code" in q:
        return ["github", "jira", "confluence", "slack"]
    return ["slack", "jira", "confluence", "salesforce", "github"]


def answer_question(req: AgentAnswerRequest) -> dict[str, Any]:
    source_systems = infer_sources(req.question)
    project_key = "ORION" if "orion" in req.question.lower() else None
    search = run_hybrid_search(SearchRequest(
        query=req.question,
        source_systems=source_systems,
        project_key=project_key,
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
    if results:
        lead = results[0]
        answer = (
            "The strongest retrieved evidence points to an operational delay connected to "
            f"{lead['title']} ({lead['source_system']}:{lead['external_id']}). "
            "Related records across conversations, tickets, customer cases, docs, and code provide the supporting trail. "
            "Review the citations before taking action."
        )
    else:
        answer = "No strong evidence was retrieved for this question. Try broadening filters or adding more sources."
    return {
        "question": req.question,
        "run_id": search["run_id"],
        "plan": [
            "decompose_question",
            "search_evidence with inferred source filters",
            "collect top ranked evidence",
            "synthesize extractive cited answer",
        ],
        "answer": answer,
        "citations": citations,
        "results": results,
    }
