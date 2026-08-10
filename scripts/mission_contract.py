#!/usr/bin/env python3
"""Validate the mission contract, including against the live database.

`data/evals/mosaic_labs_missions.json` is the single source of truth for the
workshop's missions, timings and assertions. Nothing validated it. `make
validate` reads a different file (`data/evals/queries.jsonl`) and
`scripts/catalog_contract.py` reimplements filter logic by hand, so it does not
know `max_price_cents`, `in_stock_only`, or the refurbished and sponsored
exclusions the real SQL applies. Two missions shipped that cannot pass.

This module is the only thing that validates the contract. Where a check needs
filter semantics it calls `mosaic_search.matches_filters` **on the cluster**
rather than reimplementing it, because the reimplementation is what failed.

Usage
-----
    python scripts/mission_contract.py                    # shape + live if DSN
    python scripts/mission_contract.py --shape-only       # never touch the DB
    MISSION_GATE_REQUIRE_DB=1 python scripts/mission_contract.py   # CI mode

Exit codes
----------
    0  every check that ran passed, and nothing was silently skipped
    1  a check failed, or a live check could not run in CI-with-DSN mode
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from service.assertions import (  # noqa: E402  (path set above)
    KNOWN_ASSERTIONS,
    SIGNAL_ASSERTIONS,
)

CONTRACT = REPO / "data" / "evals" / "mosaic_labs_missions.json"
STAGE_UNION_SOURCE = REPO / "ui" / "src" / "labMissions.ts"

TIMED_MISSION_COUNT = 3
LAB_FRAME_MINUTES = 40
NOMINAL_MINUTES = 40
CEILING_MINUTES = 45

# Fields a retired mission must keep. Enumerated rather than "all fields"
# because the point is to name what breaks: docs/intentional-gaps.md keys GAP-1
# and GAP-2 by `id` and cites `query`, `target_product_ids` and the assertion
# that turns green; scripts/run_eval.py consumes `query`, `filters`,
# `target_product_ids` and `top_k`.
REQUIRED_RETIRED_FIELDS = (
    "id",
    "stage",
    "title",
    "query",
    "filters",
    "target_product_ids",
    "expected_techniques",
    "checkpoint",
    "expected_outcome",
    "assertions",
    "top_k",
    "duration_minutes",
)


class Report:
    """Collects failures so one run reports every problem, not just the first."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.passed: list[str] = []

    def check(self, rule: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed.append(rule)
        else:
            self.failures.append(f"{rule}: {detail}")
        return ok

    def fail(self, rule: str, detail: str) -> None:
        self.failures.append(f"{rule}: {detail}")

    def warn(self, detail: str) -> None:
        self.warnings.append(detail)


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def split_missions(contract: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Return (timed, retired).

    Unit B introduces an explicit `self_paced` list. Until then the timed set is
    whatever carries `core: true`, so this gate reports the true count on the
    current contract instead of failing to parse it.
    """
    if "self_paced" in contract:
        return list(contract["missions"]), list(contract["self_paced"])
    timed = [m for m in contract["missions"] if m.get("core")]
    retired = [m for m in contract["missions"] if not m.get("core")]
    return timed, retired


def stage_union() -> set[str]:
    """Parse the `MosaicLabStage` union out of the TypeScript source."""
    source = STAGE_UNION_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"export type MosaicLabStage\s*=\s*([^;]+);", source)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def check_shape(contract: dict[str, Any], report: Report) -> None:
    timed, retired = split_missions(contract)
    session = contract["session"]

    # A1.5 runs first and every later check reads fields through `.get`, so a
    # mission missing a required field is *reported* rather than crashing the
    # gate. A gate that raises tells the reader less than one that names the
    # rule, and the fields checked here are exactly the ones later rules read.
    for mission in retired:
        missing = [f for f in REQUIRED_RETIRED_FIELDS if f not in mission]
        report.check(
            f"A1.5 retired mission {mission.get('id', '<no id>')} retains "
            f"required fields",
            not missing,
            f"missing {missing}",
        )

    # A1.1 — exactly three timed missions.
    report.check(
        "A1.1 timed mission count",
        len(timed) == TIMED_MISSION_COUNT,
        f"expected {TIMED_MISSION_COUNT} timed missions, found {len(timed)}: "
        f"{[m['id'] for m in timed]}",
    )

    # A1.2 — the lists are disjoint and cover every mission exactly once.
    timed_ids = [m.get("id", "<no id>") for m in timed]
    retired_ids = [m.get("id", "<no id>") for m in retired]
    overlap = sorted(set(timed_ids) & set(retired_ids))
    report.check(
        "A1.2 lists disjoint",
        not overlap,
        f"missions in both lists: {overlap}",
    )
    duplicates = sorted(
        {i for i in timed_ids + retired_ids if (timed_ids + retired_ids).count(i) > 1}
    )
    report.check(
        "A1.2 no duplicate ids",
        not duplicates,
        f"duplicate mission ids: {duplicates}",
    )

    # A1.3 — the stage union covers both lists, with no orphan members.
    declared = stage_union()
    used = {m["stage"] for m in timed + retired if "stage" in m}
    report.check(
        "A1.3 stage union parsed",
        bool(declared),
        f"could not parse MosaicLabStage from {STAGE_UNION_SOURCE.name}",
    )
    if declared:
        missing = sorted(used - declared)
        orphans = sorted(declared - used)
        report.check(
            "A1.3 every mission stage is in the union",
            not missing,
            f"stages used by missions but absent from MosaicLabStage: {missing}",
        )
        report.check(
            "A1.3 no orphan union members",
            not orphans,
            f"MosaicLabStage members no mission uses: {orphans}",
        )

    # A1.4 — the budget fits inside 40 nominal and does not program the ceiling.
    lab_sum = sum(m.get("duration_minutes", 0) for m in timed)
    orientation = session["orientation_minutes"]
    scorecard = session["scorecard_minutes"]
    programmed = orientation + lab_sum + scorecard
    declared_total = session["total_minutes"]

    report.check(
        "A1.4a timed durations inside the lab frame",
        lab_sum <= LAB_FRAME_MINUTES,
        f"timed durations sum to {lab_sum}, frame is {LAB_FRAME_MINUTES}",
    )
    report.check(
        "A1.4b orientation + timed + scorecard inside nominal",
        programmed <= NOMINAL_MINUTES,
        f"{orientation} + {lab_sum} + {scorecard} = {programmed}, "
        f"nominal is {NOMINAL_MINUTES}",
    )
    # Strictly less than the ceiling: a declared total of exactly 45 allocates
    # every minute of buffer as content and is a failure, not a pass.
    report.check(
        "A1.4c declared total leaves the ceiling band unallocated",
        declared_total <= NOMINAL_MINUTES,
        f"session.total_minutes is {declared_total}; must be <= "
        f"{NOMINAL_MINUTES} so the {NOMINAL_MINUTES}-{CEILING_MINUTES} band "
        f"stays empty (ceiling {CEILING_MINUTES} is not a target)",
    )

    # A1.6 — every named assertion resolves in service.assertions.
    for mission in timed + retired:
        unknown = sorted(set(mission.get("assertions", [])) - KNOWN_ASSERTIONS)
        report.check(
            f"A1.6 {mission.get('id', '<no id>')} assertions are defined",
            not unknown,
            f"undefined assertion(s) {unknown}; add to service/assertions.py "
            f"or fix the contract",
        )

    # A1.7 — declares implies asserts, total over the arms that have a signal
    # assertion. The converse is deliberately not checked.
    technique_to_assertion = {v: k for k, v in SIGNAL_ASSERTIONS.items()}
    for mission in timed + retired:
        declared_arms = set(mission.get("expected_techniques", []))
        carried = set(mission.get("assertions", []))
        for technique in sorted(declared_arms & set(technique_to_assertion)):
            needed = technique_to_assertion[technique]
            report.check(
                f"A1.7 {mission.get('id', '<no id>')} declares {technique} "
                f"implies asserts",
                needed in carried,
                f"declares {technique!r} in expected_techniques but does not "
                f"assert {needed!r}; the arm could return nothing without "
                f"failing anything",
            )


def check_live(contract: dict[str, Any], dsn: str, report: Report) -> None:
    """Validate targets against the cluster using production filter logic."""
    import psycopg

    timed, retired = split_missions(contract)
    missions = timed + retired

    with psycopg.connect(dsn, connect_timeout=20) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            for mission in missions:
                filters = json.dumps(mission.get("filters", {}))
                for product_id in mission.get("target_product_ids", []):
                    label = f"{mission['id']}/{product_id}"

                    # A2.8 — the target exists at all.
                    cursor.execute(
                        "SELECT 1 FROM mosaic.product WHERE product_id = %s",
                        (product_id,),
                    )
                    if cursor.fetchone() is None:
                        report.fail(
                            f"A2.8 {label} target resolves",
                            f"product_id {product_id} is not in mosaic.product",
                        )
                        continue
                    report.passed.append(f"A2.8 {label} target resolves")

                    # A2.9 — the target satisfies its own filters, judged by the
                    # production function rather than a reimplementation.
                    cursor.execute(
                        """
                        SELECT mosaic_search.matches_filters(d, %s::jsonb)
                        FROM mosaic_search.product_document d
                        WHERE d.product_id = %s
                        """,
                        (filters, product_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        report.fail(
                            f"A2.9 {label} satisfies its own filters",
                            f"product_id {product_id} is absent from "
                            f"mosaic_search.product_document, so the retrieval "
                            f"projection cannot return it",
                        )
                        continue
                    if not row[0]:
                        report.fail(
                            f"A2.9 {label} satisfies its own filters",
                            f"mosaic_search.matches_filters rejects the target "
                            f"under its own filters {filters}; "
                            f"{_diagnose(cursor, product_id, mission)}",
                        )
                    else:
                        report.passed.append(f"A2.9 {label} satisfies its own filters")

                    # A2.10 — every attribute key the filter names exists.
                    for key in mission.get("filters", {}).get("attributes") or {}:
                        cursor.execute(
                            """
                            SELECT attributes ? %s
                            FROM mosaic_search.product_document
                            WHERE product_id = %s
                            """,
                            (key, product_id),
                        )
                        present = cursor.fetchone()
                        report.check(
                            f"A2.10 {label} attribute {key!r} exists",
                            bool(present and present[0]),
                            f"filters.attributes names {key!r}, which the "
                            f"target does not carry; "
                            f"{_nearest_keys(cursor, product_id, key)}",
                        )


def _diagnose(cursor: Any, product_id: int, mission: dict) -> str:
    """Explain which constraint a rejected target violates."""
    cursor.execute(
        """
        SELECT domain::text, price_cents, availability::text,
               is_refurbished, is_sponsored
        FROM mosaic_search.product_document WHERE product_id = %s
        """,
        (product_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return "target not in the retrieval projection"
    domain, price, availability, refurbished, sponsored = row
    filters = mission.get("filters", {})
    reasons = []
    if "domain" in filters and filters["domain"] != domain:
        reasons.append(f"domain is {domain!r}, filter wants {filters['domain']!r}")
    if "max_price_cents" in filters and price > filters["max_price_cents"]:
        reasons.append(f"price_cents {price} exceeds {filters['max_price_cents']}")
    if filters.get("in_stock_only") and availability not in {"in_stock", "low_stock"}:
        reasons.append(f"availability is {availability!r}")
    if refurbished and not filters.get("include_refurbished"):
        reasons.append(
            "is_refurbished is true and include_refurbished is not set, so the "
            "default excludes it"
        )
    if sponsored and not filters.get("include_sponsored"):
        reasons.append(
            "is_sponsored is true and include_sponsored is not set, so the "
            "default excludes it"
        )
    return "; ".join(reasons) if reasons else "cause is in filters.attributes"


def _nearest_keys(cursor: Any, product_id: int, key: str) -> str:
    """Suggest the key the author probably meant."""
    cursor.execute(
        "SELECT jsonb_object_keys(attributes) FROM mosaic_search.product_document "
        "WHERE product_id = %s",
        (product_id,),
    )
    keys = [r[0] for r in cursor.fetchall()]
    stem = key.split("_")[0]
    near = [k for k in keys if stem and stem in k]
    return f"did you mean one of {near}?" if near else f"target carries {keys}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shape-only",
        action="store_true",
        help="Run shape checks only; never open a database connection",
    )
    args = parser.parse_args()

    contract = load_contract()
    report = Report()
    check_shape(contract, report)

    require_db = os.getenv("MISSION_GATE_REQUIRE_DB") == "1"
    dsn = os.getenv("DATABASE_URL")

    if args.shape_only:
        report.warn("live checks skipped: --shape-only")
    elif not dsn:
        message = (
            "CANNOT VERIFY: DATABASE_URL is not set, so A2.8 to A2.10 did not "
            "run. Mission targets are unvalidated against the cluster."
        )
        if require_db:
            report.fail("A2 live checks", message)
        else:
            report.warn(message)
    else:
        try:
            check_live(contract, dsn, report)
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            message = (
                f"CANNOT VERIFY: live checks could not complete "
                f"({type(error).__name__}: {error})"
            )
            if require_db:
                report.fail("A2 live checks", message)
            else:
                report.warn(message)

    print(f"mission contract gate: {len(report.passed)} check(s) passed")
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if report.failures:
        print(f"\n{len(report.failures)} failure(s):", file=sys.stderr)
        for failure in report.failures:
            print(f"  FAIL {failure}", file=sys.stderr)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
