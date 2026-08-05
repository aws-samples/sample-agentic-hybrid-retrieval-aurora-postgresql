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


def _live_keys() -> dict[str, object]:
    with get_dict_conn("app_engineer") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  incident_item.external_key AS incident,
                  (
                    SELECT change_item.external_key
                    FROM casework.incident_changes relation
                    JOIN casework.evidence_items change_item
                      ON change_item.evidence_id = relation.change_evidence_id
                    WHERE relation.incident_evidence_id = incident.evidence_id
                      AND relation.relationship = 'confirmed'
                    ORDER BY change_item.source_updated_at
                    LIMIT 1
                  ) AS confirmed_change,
                  (
                    SELECT lock_item.external_key
                    FROM casework.lock_evidence lock_evidence
                    JOIN casework.evidence_items lock_item
                      ON lock_item.evidence_id = lock_evidence.evidence_id
                    WHERE lock_evidence.incident_evidence_id = incident.evidence_id
                    ORDER BY lock_evidence.captured_at
                    LIMIT 1
                  ) AS lock,
                  (
                    SELECT array_agg(related.external_key ORDER BY related.external_key)
                    FROM (
                      SELECT incident_item.external_key AS external_key
                      UNION
                      SELECT change_item.external_key
                      FROM casework.incident_changes relation
                      JOIN casework.evidence_items change_item
                        ON change_item.evidence_id = relation.change_evidence_id
                      WHERE relation.incident_evidence_id = incident.evidence_id
                      UNION
                      SELECT lock_item.external_key
                      FROM casework.lock_evidence lock_evidence
                      JOIN casework.evidence_items lock_item
                        ON lock_item.evidence_id = lock_evidence.evidence_id
                      WHERE lock_evidence.incident_evidence_id = incident.evidence_id
                    ) related
                  ) AS related_keys
                FROM casework.incidents incident
                JOIN casework.evidence_items incident_item
                  ON incident_item.evidence_id = incident.evidence_id
                JOIN casework.incident_capture_runs capture
                  ON capture.incident_evidence_id = incident.evidence_id
                 AND capture.wave = 'A'
                WHERE capture.capture_origin = 'participant_induced'
                ORDER BY capture.capture_started_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    if (
        not row
        or not row["confirmed_change"]
        or not row["lock"]
        or not row["related_keys"]
    ):
        raise RuntimeError(
            "the live capture lacks its incident, confirmed backfill change, "
            "or primary lock evidence"
        )
    confirmed_change = row["confirmed_change"]
    if not isinstance(confirmed_change, str):
        raise RuntimeError("the confirmed live change has no external key")
    return {
        "incident": row["incident"],
        "confirmed_change": confirmed_change,
        "lock": row["lock"],
        "related_keys": list(row["related_keys"]),
        "fuzzy_change": confirmed_change.replace("CHG-", "CGH-", 1),
    }


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
        keys = _live_keys()
        receipts["live_keys"] = keys
        with get_dict_conn("app_engineer") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT retrieval.assert_search_index_ready() AS health")
                receipts["search_index"] = cursor.fetchone()["health"]

        lexical = run_hybrid_search(
            SearchRequest(
                query=str(keys["confirmed_change"]),
                mode="lexical",
                source_systems=["pg_incident_capture"],
                rerank=False,
                limit=5,
            )
        )
        _require(
            _keys(lexical)[0] == keys["confirmed_change"],
            f"exact identifier was not lexical rank 1: {_keys(lexical)}",
        )
        receipts["lexical_run_id"] = lexical["run_id"]

        fuzzy = run_hybrid_search(
            SearchRequest(
                query=str(keys["fuzzy_change"]),
                mode="fuzzy",
                kinds=["change"],
                source_systems=["pg_incident_capture"],
                rerank=False,
                limit=5,
            )
        )
        _require(
            _keys(fuzzy)[0] == keys["confirmed_change"],
            (
                f"mistyped identifier did not resolve to "
                f"{keys['confirmed_change']}: {_keys(fuzzy)}"
            ),
        )
        receipts["fuzzy_run_id"] = fuzzy["run_id"]

        traversal = follow_evidence_links_impl(
            [str(keys["incident"])],
            role="app_engineer",
            max_depth=2,
        )
        traversal_keys = {row["external_key"] for row in traversal["reached"]}
        _require(
            set(keys["related_keys"]) <= traversal_keys,
            f"live incident relationships were incomplete: {sorted(traversal_keys)}",
        )
        receipts["traversal_keys"] = sorted(traversal_keys)

        if os.environ.get("SMOKE_SKIP_ANSWER") == "1":
            receipts["answer"] = "skipped by SMOKE_SKIP_ANSWER=1"
        else:
            answer = answer_question(
                AgentAnswerRequest(
                    question=(
                        f"What does the captured evidence for {keys['incident']} "
                        "show about the blocked requests, the measured recovery, "
                        "and the remaining query-plan behavior?"
                    ),
                    source_systems=["pg_incident_capture"],
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
