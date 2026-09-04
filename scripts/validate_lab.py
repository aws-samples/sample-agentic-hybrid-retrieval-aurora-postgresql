#!/usr/bin/env python3
"""Validate each DAT410 lab through the production HTTP and retrieval paths.

Transport only. Every acceptance condition lives in `service.lab_checks`, which
`service/lab_proof.py` also calls, so the terminal and the browser cannot
disagree about whether a lab is finished. This file fetches the evidence those
checks need over HTTP and raises on the first failure, which is what a Makefile
target wants; the endpoint returns every verdict at once, which is what a page
wants.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from service import lab_checks
from service.lab_checks import AgentEvidence, LabCheck, RetrievalReceipt


class LabValidationError(RuntimeError):
    """A lab failed one of its participant-visible acceptance checks."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LabValidationError(message)


def _request(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise LabValidationError(
            f"{path} returned HTTP {error.code}: {detail}"
        ) from error
    except URLError as error:
        raise LabValidationError(
            f"{path} is unavailable at {base_url}: {error.reason}; "
            "start mosaic-api and retry"
        ) from error


def _mission(stage: str) -> dict[str, Any]:
    return lab_checks.load_mission(stage)


def _case(case_id: str) -> dict[str, Any]:
    return lab_checks.load_case(case_id)


def _search(base_url: str, mission: dict[str, Any]) -> dict[str, Any]:
    return _request(
        base_url,
        "/api/search",
        {
            "query": mission["query"],
            "filters": mission["filters"],
            "limit": mission["top_k"],
            "include_diagnostics": True,
            "rerank": True,
        },
    )


def _graded(checks: list[LabCheck]) -> list[str]:
    """Raise on the first failed check, then report what was proven."""
    for check in checks:
        _require(check.passed, check.detail)
    return [check.name for check in checks]


def validate_lab_1(base_url: str) -> list[str]:
    mission = _mission("retrieve")
    return _graded(lab_checks.lab_1_checks(mission, _search(base_url, mission)))


def validate_lab_2(base_url: str) -> list[str]:
    mission = _mission("rank")
    first = _search(base_url, mission)
    second = _search(base_url, mission)
    return _graded(lab_checks.lab_2_checks(mission, first, second))


def _receipts(base_url: str, agent: dict[str, Any]) -> tuple[RetrievalReceipt, ...]:
    """Fetch the persisted candidate set behind every successful search step."""
    return tuple(
        RetrievalReceipt(
            search_event_id=str(step["retrieval_run_id"]),
            query=str((step.get("arguments") or {}).get("query", "")),
            candidate_product_ids=frozenset(
                int(candidate["product_id"])
                for candidate in (
                    _request(
                        base_url,
                        f"/api/retrieval/events/{step['retrieval_run_id']}",
                    ).get("candidates")
                    or []
                )
            ),
        )
        for step in lab_checks.successful_steps(agent, "search_products")
        if step.get("retrieval_run_id")
    )


def _plans(
    base_url: str,
    mission: dict[str, Any],
    agent: dict[str, Any],
    receipts: tuple[RetrievalReceipt, ...],
) -> tuple[Any, Any]:
    """Capture and then replay the explained event's EXPLAIN plan.

    Nothing is captured unless the mission asks for a plan and the explanation
    is already bound to a receipt this turn produced: capturing runs `ANALYZE`,
    so an unbound explanation must not cost a query to report as unbound. The
    replay is a second read taken after the capture on purpose -- reusing the
    receipt fetched above would prove the plan existed, not that it landed.
    """
    event_id = lab_checks.explained_search_event_id(agent)
    if not mission.get("requires_explain_plan") or event_id not in {
        receipt.search_event_id for receipt in receipts
    }:
        return None, None
    captured = _request(base_url, f"/api/retrieval/events/{event_id}/plan", {}).get(
        "plan"
    )
    replayed = (
        _request(base_url, f"/api/retrieval/events/{event_id}").get("run") or {}
    ).get("plan_json")
    return captured, replayed


def _resolved_evidence(
    base_url: str,
    agent: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    return {
        citation["evidence_id"]: _request(
            base_url, f"/api/evidence/{citation['evidence_id']}"
        )
        for citation in agent.get("citations") or []
    }


def validate_agent_response(
    base_url: str,
    mission: dict[str, Any],
    agent: dict[str, Any],
) -> list[str]:
    """Grade one agent answer, fetching every receipt the checks compare against."""
    receipts = _receipts(base_url, agent)
    captured_plan, replayed_plan = _plans(base_url, mission, agent, receipts)
    evidence = AgentEvidence(
        receipts=receipts,
        resolved_evidence=_resolved_evidence(base_url, agent),
        captured_plan=captured_plan,
        replayed_plan=replayed_plan,
    )
    return _graded(lab_checks.agent_response_checks(mission, agent, evidence))


def validate_lab_3(base_url: str) -> list[str]:
    checks: list[str] = []
    for mission in (_mission("reason"), _case("evidence-grounding")):
        agent = _request(
            base_url,
            "/api/agent/answer",
            {
                "question": mission["query"],
                "filters": mission["filters"],
                "result_limit": mission["top_k"],
            },
        )
        checks.extend(
            f"{mission['canonical_query_id']}: {check}"
            for check in validate_agent_response(base_url, mission, agent)
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    checks = {
        1: validate_lab_1,
        2: validate_lab_2,
        3: validate_lab_3,
    }[args.lab](args.api_url)
    for check in checks:
        print(f"PASS: {check}")
    print(f"Lab {args.lab}: production-path validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
