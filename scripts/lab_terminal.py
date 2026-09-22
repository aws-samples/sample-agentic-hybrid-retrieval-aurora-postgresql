#!/usr/bin/env python3
"""Run the application once, then prepare its exact IDs for inspection in psql."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.investigate_lab import paired_searches
from scripts.validate_lab import LabValidationError, _request, _require, _search
from service import lab_checks


def request_payload(mission: dict) -> dict:
    """Use the mission's request without maintaining another query or limit."""
    if mission["stage"] == "reason":
        return {
            "question": mission["query"],
            "filters": mission["filters"],
            "result_limit": mission["top_k"],
        }
    return {
        "query": mission["query"],
        "filters": mission["filters"],
        "limit": mission["top_k"],
        "rerank": True,
        "include_diagnostics": True,
    }


def sql_context(values: dict[str, str]) -> str:
    """Encode values as SQL text, never as executable psql or shell commands."""
    statements = ["\\set ON_ERROR_STOP on", "\\pset pager off", "\\timing off"]
    expressions = []
    for key, value in values.items():
        _require(
            re.fullmatch(r"lab_[a-z][a-z0-9_]*", key) is not None,
            f"Context name rule: invalid name {key!r}; use a lab_ identifier.",
        )
        encoded = str(value).encode().hex()
        expressions.append(f"convert_from(decode('{encoded}', 'hex'), 'UTF8') AS {key}")
    statements.append("SELECT " + ",\n       ".join(expressions) + " \\gset")
    statements.extend(
        [
            "SELECT EXISTS (SELECT 1 FROM mosaic_live_search.receipt WHERE singleton",
            "  AND dataset_id = :'lab_dataset' AND catalog_sha256 = :'lab_catalog_hash') AS lab_catalog_ok \\gset",
            "\\if :lab_catalog_ok",
            "\\else",
            "DO $$ BEGIN RAISE EXCEPTION 'Lab context: catalog mismatch' USING HINT = 'Connect psql to the Aurora database used by the application.'; END $$;",
            "\\endif",
        ]
    )
    for key, table, column in (
        ("lab_search_id", "search_event", "search_event_id"),
        ("lab_before_id", "search_event", "search_event_id"),
        ("lab_agent_id", "agent_turn", "agent_turn_id"),
        ("lab_before_agent_id", "agent_turn", "agent_turn_id"),
    ):
        if key in values:
            statements.extend(
                [
                    f"SELECT EXISTS (SELECT 1 FROM mosaic.{table} WHERE {column} = :'{key}'::uuid) AS lab_run_ok \\gset",
                    "\\if :lab_run_ok",
                    "\\else",
                    "DO $$ BEGIN RAISE EXCEPTION 'Lab context: saved run missing' USING HINT = 'Connect to the application database and reload the context.'; END $$;",
                    "\\endif",
                ]
            )
    statements.extend(
        [
            "\\echo Lab context loaded. Use BEGIN READ ONLY; before the inspection queries.",
            "\\timing on",
        ]
    )
    return "\n".join(statements) + "\n"


def failed_turn(connection, question: str, started, ended) -> dict:
    """Correlate a failed HTTP call only when exactly one persisted turn fits."""
    rows = connection.execute(
        "SELECT agent_turn_id, extracted_intent FROM mosaic.agent_turn "
        "WHERE user_message=%s AND created_at >= %s AND created_at <= %s",
        (question, started, ended),
    ).fetchall()
    _require(
        len(rows) == 1,
        f"Failed-turn identity rule: found {len(rows)} matching turns; stop concurrent runs and repeat this request.",
    )
    _require(
        rows[0]["extracted_intent"].get("usage", {}).get("error_type")
        == "GroundingContractError",
        "Failed-turn rule: the persisted error is not the lab's evidence failure; inspect Aurora connectivity and model access.",
    )
    return rows[0]


def require_broken_search(event: dict, mission: dict) -> None:
    """Do not label an empty or already repaired search as the before state."""
    rows = event.get("candidates", [])
    target = mission["target_product_ids"][0]
    _require(
        bool(rows) and all(row["product_id"] != target for row in rows),
        "Before-state rule: expected a nonempty list missing the requested product; reset and apply this lab's declared fault before saving its baseline.",
    )


def prepare(lab: int, phase: str, api_url: str, output: Path) -> Path:
    """Save a production response and a small psql context; never repair a lab."""
    from service.catalog_runtime import active_dataset
    from service.db import connect
    from service.retrieval import RetrievalService

    mission = lab_checks.load_mission({1: "retrieve", 2: "rank", 3: "reason"}[lab])
    _require(
        active_dataset() == mission["dataset_id"],
        f"Dataset rule: found {active_dataset()!r}; export MOSAIC_CATALOG_DATASET={mission['dataset_id']}.",
    )
    ready = _request(api_url, "/api/readiness")
    database = ready.get("database", {})
    _require(
        database.get("dataset_id") == mission["dataset_id"]
        and database.get("product_count")
        == database.get("embedded_product_count")
        == 500000,
        "Catalog rule: API must serve all 500,000 prepared source products and vectors; ask the facilitator to correct the environment.",
    )
    with connect() as connection:
        catalog = connection.execute(
            "SELECT dataset_id, catalog_sha256 FROM mosaic_live_search.receipt WHERE singleton"
        ).fetchone()
    _require(
        catalog
        and catalog["dataset_id"] == mission["dataset_id"]
        and catalog["catalog_sha256"] == ready["source"]["dataset_manifest_sha256"],
        "Aurora identity rule: terminal and API catalogs differ; load the same workshop environment in both.",
    )
    output.mkdir(parents=True, exist_ok=True)
    before_path = output / "before-state.json"
    payload = request_payload(mission)
    before = (
        json.loads(before_path.read_text())
        if phase == "after" and before_path.exists()
        else None
    )
    if phase == "after":
        _require(
            before is not None,
            "Pair rule: no before run; run this lab with --phase before first.",
        )
        _require(
            before["request"] == payload
            and before["catalog_hash"] == catalog["catalog_sha256"]
            and before["models"] == ready["configured_models"],
            "Pair rule: request, catalog or models changed; restore the original environment before comparing.",
        )
    print(f"Alex's request: {mission['query']}", flush=True)
    state = {
        "request": payload,
        "catalog_hash": catalog["catalog_sha256"],
        "models": ready["configured_models"],
    }
    values = {
        "lab_dataset": mission["dataset_id"],
        "lab_catalog_hash": catalog["catalog_sha256"],
        "lab_query": mission["query"],
        "lab_filters": json.dumps(mission["filters"]),
        "lab_target": str(mission["target_product_ids"][0]),
        "lab_result_limit": str(mission["top_k"]),
    }
    if lab in (1, 2):
        response = _search(api_url, mission)
        event = _request(
            api_url, f"/api/retrieval/events/{response['search_event_id']}"
        )
        _require(
            event["run"]["dataset_manifest_sha256"] == catalog["catalog_sha256"],
            "Search identity rule: event belongs to a different catalog; inspect API selection.",
        )
        if before:
            paired_searches(before["event"], event, mission)
        else:
            require_broken_search(event, mission)
        state["event"] = event
        if lab == 1:
            if before:
                vector = before["query_vector"]
            else:
                retrieval = RetrievalService()
                _require(
                    retrieval._embedder().model_id
                    == event["run"]["embedding_model_id"],
                    "Embedding identity rule: terminal and API models differ; load the same model configuration before preparing SQL.",
                )
                vector = retrieval.embed_query(event["run"]["normalized_query"])
            vector = [float(value) for value in vector]
            _require(
                len(vector) == response["diagnostics"]["embedding_dimensions"]
                and all(math.isfinite(value) for value in vector),
                "Query vector rule: invalid dimensions or values; check the configured embedding model.",
            )
            state["query_vector"] = vector
            values["lab_vector"] = json.dumps(vector)
            values["lab_control_filters"] = json.dumps(
                lab_checks.load_case("semantic-eligibility")["filters"]
            )
        values.update(
            {
                "lab_query": event["run"]["normalized_query"],
                "lab_search_id": response["search_event_id"],
                "lab_before_id": before["event"]["run"]["search_event_id"]
                if before
                else response["search_event_id"],
            }
        )
        for key, value in event["run"]["retrieval_profile"].items():
            if isinstance(value, (int, float, str)):
                values[f"lab_{key}"] = str(value)
        for product in response["results"]:
            print(f"{product['signals']['final_rank']:>2}. {product['title'][:88]}")
        run_id = response["search_event_id"]
    else:
        with connect() as connection:
            started = connection.execute("SELECT clock_timestamp() AS now").fetchone()[
                "now"
            ]
        try:
            response = _request(api_url, "/api/agent/answer", payload)
        except LabValidationError as error:
            if phase != "before" or "HTTP 503" not in str(error):
                raise
            with connect() as connection:
                ended = connection.execute(
                    "SELECT clock_timestamp() AS now"
                ).fetchone()["now"]
                turn = failed_turn(connection, mission["query"], started, ended)
            run_id = str(turn["agent_turn_id"])
            response = {"agent_run_id": run_id, "error": str(error)}
            print(
                "The agent failed with the persisted evidence-contract error. Inspect its tool activity in SQL."
            )
        else:
            run_id = response["agent_run_id"]
            with connect() as connection:
                turn = connection.execute(
                    "SELECT user_message FROM mosaic.agent_turn WHERE agent_turn_id=%s",
                    (run_id,),
                ).fetchone()
            _require(
                turn and turn["user_message"] == mission["query"],
                "Agent identity rule: returned turn does not match Alex's request; inspect the API database selection.",
            )
            _require(
                phase == "after",
                "Before-state rule: the agent answered successfully; reset Lab 3 and restart its API before saving the failed turn.",
            )
            print(response["answer"])
        values.update(
            {
                "lab_agent_id": run_id,
                "lab_before_agent_id": before["run_id"] if before else run_id,
            }
        )
    UUID(str(run_id))
    state.update({"run_id": run_id, "response": response})
    # Keep every raw run even when a participant repeats a phase.
    (output / f"run-{run_id}.json").write_text(
        json.dumps(state, indent=2, default=str) + "\n"
    )
    (output / f"{phase}-state.json").write_text(
        json.dumps(state, indent=2, default=str) + "\n"
    )
    (output / f"{phase}-response.json").write_text(
        json.dumps(response, indent=2, default=str) + "\n"
    )
    context = output / "context.psql"
    rendered_context = sql_context(values)
    context.write_text(rendered_context)
    (output / f"{phase}-context.psql").write_text(rendered_context)
    print(f"Saved the application response. In psql: \\i {context}")
    return context


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "wait"))
    parser.add_argument("--lab", type=int, choices=(1, 2, 3))
    parser.add_argument("--phase", choices=("before", "after"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "wait":
        for attempt in range(20):
            try:
                with urlopen(
                    args.api_url.rstrip("/") + "/api/health", timeout=5
                ) as response:
                    _require(
                        response.status == 200,
                        "Health rule: API is not ready; inspect the service logs.",
                    )
                print("Mosaic API is responding.")
                return 0
            except (LabValidationError, HTTPError, URLError, TimeoutError) as error:
                if attempt == 19:
                    raise LabValidationError(
                        "Health rule: API did not recover; inspect mosaic-api.service logs and retry."
                    ) from error
                time.sleep(1)
    if args.lab is None or args.phase is None:
        parser.error("run requires --lab and --phase")
    prepare(
        args.lab,
        args.phase,
        args.api_url,
        args.output or Path(f".local/lab-{args.lab}"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
