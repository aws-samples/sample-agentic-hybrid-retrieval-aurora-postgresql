#!/usr/bin/env python3
"""Capture one real retrieval run and commit it as the Observatory's first paint.

The Retrieval Observatory has to show a populated matrix the moment a participant
opens it. Four empty panels and a "run this to see anything" prompt teach nothing,
and a hand-drawn illustration teaches something false: the previous version of that
surface printed "This replay explains the retrieval flow, not a measured run", which
is an admission that the numbers on screen were invented.

So the first paint is a real run, captured through the live API and committed. It is
labelled as a capture with its own date and run id, and pressing Run pipeline
replaces it with a fresh one. Nothing on the surface is ever unmeasured.

This producer exists so the seed cannot be edited by hand into agreement with a
claim somebody wants to make. `ui/src/retrievalSeed.test.ts` re-derives the fusion
arithmetic from the committed file, which a hand-written response fails.

Usage
-----
    uv run python scripts/capture_retrieval_seed.py
    uv run python scripts/capture_retrieval_seed.py --mission exact-identity
    uv run python scripts/capture_retrieval_seed.py --api http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MISSIONS = REPO / "data" / "evals" / "mosaic_labs_missions.json"
SEED = REPO / "ui" / "src" / "data" / "retrievalSeedRun.json"

# The Observatory selects this scenario first, so it is the run that has to be
# on screen before anybody presses anything.
DEFAULT_MISSION = "typo-recovery"
DEFAULT_API = "http://127.0.0.1:8010"
RESULT_LIMIT = 12


def load_mission(mission_id: str) -> dict[str, Any]:
    """Return the mission definition the UI will replay, by id.

    Args:
        mission_id: Mission or supporting-check id from the missions manifest.

    Returns:
        The mission object, carrying at least `query` and `filters`.

    Raises:
        SystemExit: If the manifest has no mission with that id.
    """
    manifest = json.loads(MISSIONS.read_text(encoding="utf-8"))
    for mission in manifest["missions"] + manifest["supporting_checks"]:
        if mission["id"] == mission_id:
            return mission
    known = sorted(
        entry["id"] for entry in manifest["missions"] + manifest["supporting_checks"]
    )
    raise SystemExit(f"Unknown mission {mission_id!r}. Known ids: {', '.join(known)}")


def capture(api: str, mission: dict[str, Any]) -> dict[str, Any]:
    """Run the mission's query against a live Mosaic API and return the response.

    Args:
        api: Base URL of a running Mosaic API.
        mission: Mission definition supplying the query and structured filters.

    Returns:
        The decoded `/api/search` response.

    Raises:
        SystemExit: If the API is unreachable or rejects the request.
    """
    payload = json.dumps(
        {
            "query": mission["query"],
            "filters": mission["filters"],
            "limit": RESULT_LIMIT,
            "rerank": True,
        }
    ).encode()
    request = urllib.request.Request(
        f"{api.rstrip('/')}/api/search",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"The API rejected the capture ({error.code}): {error.read()[:400]!r}"
        ) from error
    except OSError as error:
        raise SystemExit(
            f"No Mosaic API answered at {api}. Start it (`make api`) and retry: {error}"
        ) from error


def assert_measured(response: dict[str, Any]) -> None:
    """Refuse to commit a response that cannot have come from the pipeline.

    Every returned row must carry the fusion arithmetic the SQL performs, so a
    response assembled by hand cannot pass through this producer.

    Args:
        response: A decoded `/api/search` response.

    Raises:
        SystemExit: If a row is missing signals or its contributions do not match
            `1 / (k + rank)` for the ranks it reports.
    """
    profile = (response.get("diagnostics") or {}).get("retrieval_profile") or {}
    rrf_k = profile.get("rrf_k")
    if not isinstance(rrf_k, int):
        raise SystemExit("The response carries no retrieval_profile.rrf_k to check.")

    for row in response["results"]:
        signals = row.get("signals")
        if not signals:
            raise SystemExit(f"Product {row['product_id']} came back without signals.")
        total = 0.0
        for arm in ("fts", "trigram", "semantic"):
            rank = signals[arm]["rank"]
            contribution = signals[arm]["rrf_contribution"]
            if rank is None:
                if contribution is not None:
                    raise SystemExit(
                        f"Product {row['product_id']} has no {arm} rank but reports a "
                        f"{arm} contribution of {contribution}."
                    )
                continue
            expected = 1.0 / (rrf_k + rank)
            if abs(contribution - expected) > 1e-9:
                raise SystemExit(
                    f"Product {row['product_id']} reports {arm} rank {rank} with "
                    f"contribution {contribution}, but 1/({rrf_k}+{rank}) is {expected}."
                )
            total += contribution
        if abs(signals["rrf_score"] - total) > 1e-9:
            raise SystemExit(
                f"Product {row['product_id']} reports rrf_score "
                f"{signals['rrf_score']}, but its arm contributions sum to {total}."
            )

    ranks = sorted(row["signals"]["final_rank"] for row in response["results"])
    if ranks != list(range(1, len(ranks) + 1)):
        raise SystemExit(f"final_rank is not a dense 1..n ordering: {ranks}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", default=DEFAULT_MISSION)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    mission = load_mission(args.mission)
    response = capture(args.api, mission)
    assert_measured(response)

    seed = {
        "provenance": {
            "captured_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "mission_id": mission["id"],
            "producer": "scripts/capture_retrieval_seed.py",
            "search_event_id": response["search_event_id"],
            "note": (
                "One real Aurora retrieval run, captured through /api/search so the "
                "Observatory opens on measured ranks. Run pipeline replaces it."
            ),
        },
        "response": response,
    }
    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(json.dumps(seed, indent=1) + "\n", encoding="utf-8")

    arms = {
        arm: sum(
            1 for row in response["results"] if row["signals"][arm]["rank"] is not None
        )
        for arm in ("fts", "trigram", "semantic")
    }
    print(f"Captured {mission['id']} run {response['search_event_id'][:8]} -> {SEED}")
    print(f"  {len(response['results'])} rows; arms contributing: {arms}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
