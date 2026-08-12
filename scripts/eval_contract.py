"""Resolve canonical eval records without duplicating authoritative lab queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MISSION_CONTRACT = REPO / "data" / "evals" / "mosaic_labs_missions.json"


def load_evaluation_queries(
    path: Path,
    *,
    mission_contract: Path = MISSION_CONTRACT,
) -> list[dict[str, Any]]:
    """Load JSONL evals and resolve mission-backed query text and filters."""
    queries = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contract = json.loads(mission_contract.read_text(encoding="utf-8"))
    missions = {
        item["id"]: item
        for item in contract["missions"] + contract.get("supporting_checks", [])
    }
    resolved: list[dict[str, Any]] = []
    for query in queries:
        mission_id = query.get("mission_id")
        if not mission_id:
            resolved.append(query)
            continue
        if "query" in query or "filters" in query:
            raise ValueError(
                f"{query.get('query_id', '<missing>')} duplicates query or filters "
                f"owned by mission {mission_id}; remove those fields"
            )
        mission = missions.get(str(mission_id))
        if mission is None:
            raise ValueError(
                f"{query.get('query_id', '<missing>')} references unknown mission "
                f"{mission_id!r}"
            )
        expected_query_id = mission.get("canonical_query_id")
        if expected_query_id != query.get("query_id"):
            raise ValueError(
                f"{mission_id} canonical_query_id is {expected_query_id!r}, "
                f"not {query.get('query_id')!r}"
            )
        resolved.append(
            {
                **query,
                "query": mission["query"],
                "filters": mission["filters"],
            }
        )
    return resolved
