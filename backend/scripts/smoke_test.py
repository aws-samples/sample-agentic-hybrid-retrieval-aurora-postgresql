from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import answer_question, follow_evidence_links_impl  # noqa: E402
from app.db import close_pool, get_dict_conn  # noqa: E402
from app.models import AgentAnswerRequest, SearchRequest  # noqa: E402
from app.search import run_hybrid_search  # noqa: E402


def _keys(result: dict) -> list[str]:
    return [row["external_key"] for row in result["results"]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _readiness_path() -> Path:
    configured = os.environ.get("WORKBENCH_READINESS_FILE")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "READINESS.md"


def _write_readiness(receipts: dict[str, object]) -> Path | None:
    """Record the smoke run_id in the readiness report (bootstrap stage S8).

    Gate G-13 reads the ``smoke run_id`` line from this report to know which run
    to reproduce. Only the answer POST produces a run_id worth verifying, so this
    writes nothing when the answer step was skipped.
    """
    run_id = receipts.get("answer_run_id")
    if not run_id:
        return None
    path = _readiness_path()
    body = "\n".join(
        [
            "# Hybrid Retrieval Workbench readiness report",
            "",
            f"smoke run_id: {run_id}",
            f"citation count: {receipts.get('citation_count')}",
            f"synthesis mode: {receipts.get('synthesis_mode')}",
            "",
            "## Smoke receipts",
            "",
            "```json",
            json.dumps(receipts, indent=2, default=str),
            "```",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


def main() -> int:
    receipts: dict[str, object] = {}
    try:
        with get_dict_conn("analyst") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT retrieval.assert_search_index_ready() AS health")
                receipts["search_index"] = cursor.fetchone()["health"]

        lexical = run_hybrid_search(
            SearchRequest(
                query="Why did CHG-1842 block writes on checkout-prod-cluster-01?",
                mode="lexical",
                cluster_id="checkout-prod-cluster-01",
                rerank=False,
                limit=5,
            )
        )
        _require(
            _keys(lexical)[0] == "CHG-1842",
            f"exact identifier was not lexical rank 1: {_keys(lexical)}",
        )
        receipts["lexical_run_id"] = lexical["run_id"]

        fuzzy = run_hybrid_search(
            SearchRequest(
                query="CGH-1842",
                mode="fuzzy",
                kinds=["change"],
                environment="production",
                rerank=False,
                limit=5,
            )
        )
        _require(
            _keys(fuzzy)[0] == "CHG-1842",
            f"mistyped identifier did not resolve to CHG-1842: {_keys(fuzzy)}",
        )
        receipts["fuzzy_run_id"] = fuzzy["run_id"]

        hidden = run_hybrid_search(
            SearchRequest(
                query="Northstar premium checkout escalation",
                mode="lexical",
                role="analyst",
                rerank=False,
                limit=20,
            )
        )
        visible = run_hybrid_search(
            SearchRequest(
                query="Northstar premium checkout escalation",
                mode="lexical",
                role="admin",
                rerank=False,
                limit=20,
            )
        )
        _require("CASE-7421" not in _keys(hidden), "restricted case leaked")
        _require("CASE-7421" in _keys(visible), "authorized case was not retrievable")
        receipts["acl_run_ids"] = [hidden["run_id"], visible["run_id"]]

        # The ACL is enforced by the engine, so prove it by disagreement: the same
        # query under two personas must return different row counts.
        with get_dict_conn("analyst") as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) AS visible
                    FROM casework.evidence_items
                    WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
                    """
                )
                analyst_visible = cursor.fetchone()["visible"]
        with get_dict_conn("admin") as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) AS visible
                    FROM casework.evidence_items
                    WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
                    """
                )
                admin_visible = cursor.fetchone()["visible"]
        _require(
            analyst_visible == 0,
            f"analyst saw {analyst_visible} restricted evidence rows; RLS is not enforced",
        )
        _require(
            admin_visible > 0,
            "admin saw no restricted evidence rows; either the seed has none or "
            "can_see_restricted is not granted",
        )
        receipts["acl_row_counts"] = {
            "analyst": analyst_visible,
            "admin": admin_visible,
        }

        traversal = follow_evidence_links_impl(
            ["INC-2047"],
            role="analyst",
            max_depth=2,
        )
        traversal_keys = {row["external_key"] for row in traversal["reached"]}
        _require("CASE-7419" in traversal_keys, "visible support case was not traversed")
        _require("CASE-7421" not in traversal_keys, "restricted case leaked in traversal")
        receipts["traversal_keys"] = sorted(traversal_keys)

        if os.environ.get("SMOKE_SKIP_ANSWER") == "1":
            receipts["answer"] = "skipped by SMOKE_SKIP_ANSWER=1"
        else:
            answer = answer_question(
                AgentAnswerRequest(
                    question=(
                        "Why did CHG-1842 block checkout writes during INC-2047, "
                        "which visible customer was affected, and what was the safe fix?"
                    ),
                    limit=8,
                )
            )
            _require(answer["citations"], "agent answer returned no citations")
            _require(
                all(citation.get("source_revision") for citation in answer["citations"]),
                "citation source revisions are missing",
            )
            if os.environ.get("SMOKE_REQUIRE_BEDROCK") == "1":
                _require(
                    answer["synthesis"]["mode"] == "bedrock",
                    f"expected Bedrock synthesis: {answer['synthesis']}",
                )
            receipts["answer_run_id"] = answer["run_id"]
            receipts["citation_count"] = len(answer["citations"])
            receipts["synthesis_mode"] = answer["synthesis"]["mode"]

        print(json.dumps(receipts, indent=2, default=str))
        readiness = _write_readiness(receipts)
        if readiness:
            print(f"readiness report: {readiness}")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
