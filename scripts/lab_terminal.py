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
from service.lab_checks import FACILITATOR
from service.participant_commands import complete_lab_3, repeat_request
from service.participant_commands import start as start_command

NEW_TERMINAL = (
    "open a new terminal from the Terminal menu; it loads the workshop settings"
)


class AlreadyRepaired(LabValidationError):
    """The search a start would save as failing already finds the requested product."""


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
            "SELECT EXISTS (SELECT 1 FROM mosaic_search.receipt WHERE singleton",
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
        "SELECT t.agent_turn_id, t.extracted_intent, "
        "(SELECT count(*) FROM mosaic.agent_tool_event e "
        " WHERE e.agent_turn_id=t.agent_turn_id AND e.tool_name='get_product_evidence' "
        " AND e.outcome='success' AND (e.output_payload->>'result_count')::int > 0) "
        " AS evidence_successes, "
        "(SELECT count(*) FROM mosaic.agent_tool_event e "
        " WHERE e.agent_turn_id=t.agent_turn_id AND e.tool_name='get_product_evidence' "
        " AND e.outcome='error') AS evidence_errors FROM mosaic.agent_turn t "
        "WHERE t.user_message=%s AND t.created_at >= %s AND t.created_at <= %s",
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
    _require(
        rows[0]["evidence_successes"] > 0 and rows[0]["evidence_errors"] == 0,
        "Evidence baseline rule: found "
        f"{rows[0]['evidence_successes']} successful and {rows[0]['evidence_errors']} "
        "failed evidence calls; inspect their saved errors and fix the environment "
        "before repeating the intentional registration failure.",
    )
    return rows[0]


TARGET_METHODS = (
    ("fts_rank", "full-text search"),
    ("trigram_rank", "fuzzy matching"),
    ("semantic_rank", "semantic search"),
)


def target_summary(event: dict, mission: dict) -> str:
    """State where the lab's target sits in the saved pool, as SQL would show it."""
    target = mission["target_product_ids"][0]
    rows = event.get("candidates", [])
    row = next((row for row in rows if row["product_id"] == target), None)
    if row is None:
        return (
            f"Target {target}: not among the {len(rows)} saved candidates, "
            "so reranking never received it."
        )
    methods = ", ".join(
        f"{label} rank {row[key]}"
        for key, label in TARGET_METHODS
        if row.get(key) is not None
    )
    return (
        f"Target {target}: combined position {row['fused_rank']}, final position "
        f"{row['result_rank']}; found by {methods or 'no method'}."
    )


def require_broken_search(event: dict, mission: dict) -> None:
    """Do not label an empty or already repaired search as the before state."""
    rows = event.get("candidates", [])
    target = mission["target_product_ids"][0]
    _require(
        bool(rows),
        f"the search returned no candidates, so there is nothing to save as the "
        f"failing request. Next: {FACILITATOR}.",
    )
    if any(row["product_id"] == target for row in rows):
        raise AlreadyRepaired(
            f"the search already finds product {target} among its {len(rows)} "
            "candidates, so there is no failing request to save"
        )


def _without_before(lab: int, output: Path) -> str:
    """Say why there is no Before to compare, or refuse when the lab never started."""
    path = output / "before-state.json"
    record_path = output / "start.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    if lab == 3:
        raise LabValidationError(
            f"there is no saved failing agent turn in {path} to compare with. Lab 3 "
            f"is checked on your own saved run instead: {complete_lab_3()}"
        )
    if not record.get("completed_at"):
        raise LabValidationError(
            f"Lab {lab} has not started, so there is no saved failing request to "
            f"compare with.\nNext: {start_command(lab)}\nThen: {repeat_request(lab)}"
        )
    if (record.get("steps", {}).get("evidence") or {}).get("search_event_id"):
        return (
            f"The saved failing request, {path}, is missing, so there is no Before "
            "to compare. This shows the search as it is now."
        )
    return (
        f"Lab {lab} started with its repair already working, so no failing request "
        "was saved and there is no Before to compare. This shows the search as it "
        "is now."
    )


def prepare(lab: int, phase: str, api_url: str, output: Path) -> Path:
    """Save a production response and a small psql context; never repair a lab."""
    from service.catalog_runtime import active_dataset
    from service.db import connect

    mission = lab_checks.load_mission({1: "retrieve", 2: "rank", 3: "reason"}[lab])
    _require(
        active_dataset() == mission["dataset_id"],
        f"this terminal selects catalog {active_dataset()!r}, not "
        f"{mission['dataset_id']!r}. Next: {NEW_TERMINAL} "
        f"(MOSAIC_CATALOG_DATASET={mission['dataset_id']}); if it still differs, "
        f"{FACILITATOR}.",
    )
    ready = _request(api_url, "/api/readiness")
    database = ready.get("database", {})
    _require(
        database.get("dataset_id") == mission["dataset_id"]
        and database.get("catalog_ready") is True,
        "the Mosaic API is not serving the complete prepared catalog. "
        f"Next: {FACILITATOR}.",
    )
    with connect() as connection:
        catalog = connection.execute(
            "SELECT dataset_id, catalog_sha256 FROM mosaic_search.receipt WHERE singleton"
        ).fetchone()
    _require(
        catalog
        and catalog["dataset_id"] == mission["dataset_id"]
        and catalog["catalog_sha256"] == ready["source"]["dataset_manifest_sha256"],
        "this terminal and the Mosaic API read different catalogs. "
        f"Next: {NEW_TERMINAL}; if it still differs, {FACILITATOR}.",
    )
    output.mkdir(parents=True, exist_ok=True)
    before_path = output / "before-state.json"
    payload = request_payload(mission)
    before = (
        json.loads(before_path.read_text())
        if phase == "after" and before_path.exists()
        else None
    )
    if phase == "after" and before is None:
        print(_without_before(lab, output), flush=True)
    elif phase == "after":
        changed = [
            label
            for label, saved, now in (
                ("request", before["request"], payload),
                ("catalog", before["catalog_hash"], catalog["catalog_sha256"]),
                ("model settings", before["models"], ready["configured_models"]),
            )
            if saved != now
        ]
        _require(
            not changed,
            f"the saved failing request, {before_path}, used a different "
            f"{' and '.join(changed)} from this search, so the two cannot be "
            f"compared. Next: {FACILITATOR}.",
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
            f"the search ran on a different catalog from this terminal's. Next: {FACILITATOR}.",
        )
        if before:
            paired_searches(before["event"], event, mission)
        elif phase == "before":
            require_broken_search(event, mission)
        state["event"] = event
        # A second model call can change source ranks even for identical text.
        vector = event["run"].get("diagnostics", {}).get("query_embedding")
        _require(
            isinstance(vector, list)
            and all(isinstance(v, (int, float)) for v in vector),
            "the search saved no query embedding, so the psql context cannot be "
            f"prepared. Next: {FACILITATOR}.",
        )
        vector = [float(value) for value in vector]
        _require(
            len(vector) == response["diagnostics"]["embedding_dimensions"]
            and all(math.isfinite(value) for value in vector),
            "the search saved a query embedding of the wrong size or with invalid "
            f"values. Next: {FACILITATOR}.",
        )
        state["query_vector"] = vector
        values["lab_vector"] = json.dumps(vector)
        if lab == 1:
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
        print(
            ("Before: absent. After: " if before else "")
            + target_summary(event, mission)
        )
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
    # The exercise grader reads the same values psql loaded, so a participant's
    # query is graded against the run they inspected, not a fresh one.
    (output / "context.json").write_text(json.dumps(values, indent=2) + "\n")
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
    try:
        prepare(
            args.lab,
            args.phase,
            args.api_url,
            args.output or Path(f".local/lab-{args.lab}"),
        )
    except LabValidationError as error:
        raise SystemExit(f"Lab {args.lab}: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
