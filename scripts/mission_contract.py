#!/usr/bin/env python3
"""Validate the lab contract, including against the live database.

`data/evals/mosaic_labs_missions.json` is the single source of truth for the
workshop's labs, retrieval checks, timings, and assertions. Package validation
and `scripts/catalog_contract.py` cover adjacent artifact and offline-filter
contracts; this gate owns mission-internal consistency and live target checks.

Where a check needs authoritative filter semantics, this module calls
`mosaic_search.matches_filters` **on the cluster** rather than treating an
offline projection as runtime proof.

Scope, deliberately bounded: this gate checks contract-internal consistency and
contract-versus-Aurora truth. It does not check lesson coverage or custody;
that is the run-of-show table's job. The missing JSONB attribute filter on
`rank-with-evidence` was invisible here by design: no contract-internal rule is
violated by a lesson going unowned, and a gate that guessed at pedagogy would be
deriving its expectations from the thing it judges.

Every failure names the rule, shows the offending value, and suggests the
nearest fix — see `explain`.

Usage
-----
    uv run python scripts/mission_contract.py                    # shape + live if DSN
    uv run python scripts/mission_contract.py --shape-only       # never touch the DB
    MISSION_GATE_REQUIRE_DB=1 uv run python scripts/mission_contract.py   # CI

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

from service.assertions import (
    ASSERTIONS,
    KNOWN_ASSERTIONS,
    SIGNAL_ASSERTIONS,
)

CONTRACT = REPO / "data" / "evals" / "mosaic_labs_missions.json"
CANONICAL_EVALS = REPO / "data" / "evals" / "canonical_queries.jsonl"
STAGE_UNION_SOURCE = REPO / "ui" / "src" / "labMissions.ts"

TIMED_MISSION_COUNT = 3
PARTICIPANT_QUERY_COUNT = 8
NOMINAL_MINUTES = 60
REQUIRED_PARTICIPANT_EDIT_FIELDS = (
    "file",
    "approximate_lines",
    "task",
    "broken_state",
    "fixed_state",
    "observe_before",
    "observe_after",
    "checkpoint_question",
)

# Fields a supporting check must keep. Enumerated rather than "all fields"
# because the point is to name what breaks. Every one is read by a live
# consumer: `ui/src/labMissions.ts` types every check and the retrieval lab
# renders a checkpoint or advanced check from the same records as a core lab
# (`expected_techniques`, `target_product_ids`, `duration_minutes`,
# `checkpoint`, and `placement`); `docs/intentional-gaps.md` keys all three gaps
# by `id` and cites `query`, `target_product_ids`, and the assertion that
# turns green.
#
# `scripts/run_eval.py` is deliberately not cited here: it consumes
# `data/evals/queries.jsonl`, not this contract.
REQUIRED_SUPPORTING_FIELDS = (
    "id",
    "stage",
    "core",
    "placement",
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


def explain(found: str, fix: str) -> str:
    """Render a failure in the house style: offending value, then nearest fix.

    House standard, adopted after `A2.10`'s "did you mean `usb_c_power_w`?"
    turned a five-minute hunt into a one-line correction. Every message shows
    what was actually found and names the specific edit that resolves it, so the
    reader never has to reconstruct the author's intent.
    """
    return f"found {found}; fix: {fix}"


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
    """Return (required labs, supporting checks).

    Version 3 separates the three required labs from their checkpoints and
    optional advanced checks. The fallback keeps the gate useful when inspecting
    an older flattened contract during release archaeology.
    """
    if "supporting_checks" in contract:
        return list(contract["missions"]), list(contract["supporting_checks"])
    timed = [m for m in contract["missions"] if not m.get("placement")]
    supporting = [m for m in contract["missions"] if m.get("placement")]
    return timed, supporting


def stage_union() -> set[str]:
    """Parse the `MosaicLabStage` union out of the TypeScript source."""
    source = STAGE_UNION_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"export type MosaicLabStage\s*=\s*([^;]+);", source)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def check_shape(contract: dict[str, Any], report: Report) -> None:
    timed, supporting = split_missions(contract)
    session = contract["session"]
    canonical_evals = [
        json.loads(line)
        for line in CANONICAL_EVALS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # A1.5 runs first and every later check reads fields through `.get`, so a
    # check missing a required field is *reported* rather than crashing the
    # gate. A gate that raises tells the reader less than one that names the
    # rule, and the fields checked here are exactly the ones later rules read.
    for mission in supporting:
        missing = [f for f in REQUIRED_SUPPORTING_FIELDS if f not in mission]
        report.check(
            f"A1.5 supporting check {mission.get('id', '<no id>')} retains "
            f"required fields",
            not missing,
            explain(
                f"{len(missing)} missing field(s) {missing}",
                "restore them on this check; ui/src/labMissions.ts types them "
                "and docs/intentional-gaps.md cites them",
            ),
        )

    # A1.1 — exactly three required labs.
    report.check(
        "A1.1 required lab count",
        len(timed) == TIMED_MISSION_COUNT,
        explain(
            f"{len(timed)} required labs {[m.get('id', '<no id>') for m in timed]}",
            f"the session funds exactly {TIMED_MISSION_COUNT}; fold smaller outcomes "
            f"into supporting_checks rather than adding another top-level lab",
        ),
    )

    # A1.2 — the lists are disjoint and cover every mission exactly once.
    timed_ids = [m.get("id", "<no id>") for m in timed]
    supporting_ids = [m.get("id", "<no id>") for m in supporting]
    overlap = sorted(set(timed_ids) & set(supporting_ids))
    report.check(
        "A1.2 lists disjoint",
        not overlap,
        explain(
            f"retrieval check(s) in both lists: {overlap}",
            "delete the duplicate entry from one list; an id is a required lab "
            "anchor or a supporting check, never both",
        ),
    )
    duplicates = sorted(
        {
            i
            for i in timed_ids + supporting_ids
            if (timed_ids + supporting_ids).count(i) > 1
        }
    )
    report.check(
        "A1.2 no duplicate ids",
        not duplicates,
        explain(
            f"repeated retrieval id(s): {duplicates}",
            "give each check a unique id; the GAP ledger keys on it",
        ),
    )

    # A1.3 — the stage union covers both lists, with no orphan members.
    declared = stage_union()
    used = {m["stage"] for m in timed + supporting if "stage" in m}
    report.check(
        "A1.3 stage union parsed",
        bool(declared),
        explain(
            f"no MosaicLabStage union in {STAGE_UNION_SOURCE.name}",
            "restore `export type MosaicLabStage = ...` so the gate can compare "
            "the contract's stages against the type the UI narrows on",
        ),
    )
    if declared:
        missing = sorted(used - declared)
        orphans = sorted(declared - used)
        report.check(
            "A1.3 every lab stage is in the union",
            not missing,
            explain(
                f"stage(s) {missing} used by checks but absent from the union",
                f"add {missing} to MosaicLabStage in {STAGE_UNION_SOURCE.name}, "
                f"or correct the check's stage to one of {sorted(declared)}",
            ),
        )
        report.check(
            "A1.3 no orphan union members",
            not orphans,
            explain(
                f"union member(s) {orphans} no mission uses",
                f"delete {orphans} from MosaicLabStage; an unused stage keeps "
                f"its UI copy alive after the mission is gone",
            ),
        )

    # A1.4 — the 60-minute program is exact. The manifest owns its allocations,
    # including a recovery buffer; this gate only proves they agree.
    lab_sum = sum(m.get("duration_minutes", 0) for m in timed)
    orientation = session["orientation_minutes"]
    declared_lab_frame = session["core_lab_minutes"]
    scorecard = session["scorecard_minutes"]
    contingency = session["contingency_minutes"]
    programmed = orientation + lab_sum + scorecard + contingency
    declared_total = session["total_minutes"]

    report.check(
        "A1.4a required lab durations match the lab frame",
        lab_sum == declared_lab_frame,
        explain(
            f"required lab durations sum to {lab_sum} against a "
            f"{declared_lab_frame}-minute frame",
            "align the three required lab durations with "
            "session.core_lab_minutes; checkpoint time is included inside "
            "its parent lab",
        ),
    )
    report.check(
        "A1.4b orientation + labs + wrap-up + contingency match nominal",
        programmed == NOMINAL_MINUTES,
        explain(
            f"{orientation} + {lab_sum} + {scorecard} + {contingency} = "
            f"{programmed} programmed "
            f"minutes against a {NOMINAL_MINUTES}-minute session",
            "align the session allocations in mosaic_labs_missions.json so "
            "they total the declared Builder's Session duration",
        ),
    )
    report.check(
        "A1.4c declared total matches the session",
        declared_total == NOMINAL_MINUTES,
        explain(
            f"session.total_minutes is {declared_total}",
            f"set it to {NOMINAL_MINUTES} for the re:Invent Builder's Session",
        ),
    )

    # A1.6 — every named assertion resolves in service.assertions.
    for mission in timed + supporting:
        unknown = sorted(set(mission.get("assertions", [])) - KNOWN_ASSERTIONS)
        report.check(
            f"A1.6 {mission.get('id', '<no id>')} assertions are defined",
            not unknown,
            explain(
                f"undefined assertion(s) {unknown}",
                f"define them in service/assertions.py with a falsifier, or "
                f"replace them with one of {sorted(KNOWN_ASSERTIONS)}",
            ),
        )

    # A1.7 — declares implies asserts, total over the arms that have a signal
    # assertion. The converse is deliberately not checked.
    technique_to_assertion = {v: k for k, v in SIGNAL_ASSERTIONS.items()}
    for mission in timed + supporting:
        declared_arms = set(mission.get("expected_techniques", []))
        carried = set(mission.get("assertions", []))
        for technique in sorted(declared_arms & set(technique_to_assertion)):
            needed = technique_to_assertion[technique]
            report.check(
                f"A1.7 {mission.get('id', '<no id>')} declares {technique} "
                f"implies asserts",
                needed in carried,
                explain(
                    f"{technique!r} in expected_techniques with no "
                    f"{needed!r} in assertions, so the arm could return nothing "
                    f"without failing anything",
                    f"either add {needed!r} to this mission's assertions, or "
                    f"remove {technique!r} from expected_techniques if the arm "
                    f"is not part of this mission's lesson",
                ),
            )

    # A1.5b — every required lab has one focused, inspectable participant edit.
    for mission in timed:
        participant_edit = mission.get("participant_edit") or {}
        missing = [
            field
            for field in REQUIRED_PARTICIPANT_EDIT_FIELDS
            if field not in participant_edit
        ]
        line_count = participant_edit.get("approximate_lines")
        before = participant_edit.get("observe_before")
        after = participant_edit.get("observe_after")
        report.check(
            f"A1.5b {mission.get('id', '<no id>')} participant edit declared",
            not missing
            and isinstance(line_count, int)
            and 5 <= line_count <= 15
            and isinstance(before, list)
            and len(before) >= 2
            and isinstance(after, list)
            and len(after) >= 2,
            explain(
                f"participant_edit={participant_edit!r}; missing={missing}",
                "declare one 5-15 line edit with file, task, broken_state, and "
                "fixed_state for this required lab",
            ),
        )

    # A1.5c — participant queries are owned by this manifest. Canonical
    # judgments link by mission ID instead of carrying a second query/filter
    # copy that can drift from Workshop Studio.
    linked_evals = {
        item.get("mission_id"): item
        for item in canonical_evals
        if item.get("mission_id")
    }
    participant_checks = timed + [
        mission for mission in supporting if mission.get("core")
    ]
    report.check(
        "A1.5c participant query count",
        len(participant_checks) == PARTICIPANT_QUERY_COUNT,
        explain(
            f"{len(participant_checks)} core participant queries",
            f"keep exactly {PARTICIPANT_QUERY_COUNT} short runs across the three "
            "labs; add controls as supporting_checks, never required labs",
        ),
    )
    for mission in participant_checks:
        canonical_query_id = mission.get("canonical_query_id")
        linked = linked_evals.get(mission.get("id"))
        report.check(
            f"A1.5c {mission.get('id', '<no id>')} owns one canonical query",
            bool(re.fullmatch(r"G-\d{3}", str(canonical_query_id)))
            and linked is not None
            and linked.get("query_id") == canonical_query_id
            and "query" not in linked
            and "filters" not in linked,
            explain(
                f"canonical_query_id={canonical_query_id!r}, linked_eval={linked!r}",
                "link one canonical eval by mission_id and remove query/filters "
                "from that eval; this manifest owns participant query text",
            ),
        )

    # A1.8 — every assertion in the vocabulary states how it can fail. An
    # assertion whose failure condition cannot occur reads as evidence while
    # proving nothing, which is the defect shape this whole phase removes.
    for name in sorted(KNOWN_ASSERTIONS):
        falsifier = ASSERTIONS[name].falsifier
        report.check(
            f"A1.8 {name} declares a falsifier",
            bool(falsifier.strip()),
            explain(
                f"{name!r} has an empty falsifier",
                "state the condition under which it fails, in "
                "service/assertions.py; if none exists, delete the assertion",
            ),
        )


def check_live(contract: dict[str, Any], dsn: str, report: Report) -> None:
    """Validate targets against the cluster using production filter logic."""
    import psycopg

    timed, supporting = split_missions(contract)
    missions = timed + supporting

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
                            explain(
                                f"product_id {product_id} is not in mosaic.product",
                                "point the mission at a product that exists on "
                                "the cluster, or reseed the catalog",
                            ),
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
                            explain(
                                f"product_id {product_id} is absent from "
                                f"mosaic_search.product_document, so no arm can "
                                f"return it",
                                "refresh the retrieval projection, or choose a "
                                "target that is projected",
                            ),
                        )
                        continue
                    if not row[0]:
                        report.fail(
                            f"A2.9 {label} satisfies its own filters",
                            explain(
                                f"mosaic_search.matches_filters rejects the "
                                f"target under this mission's own filters "
                                f"{filters} — "
                                f"{_diagnose(cursor, product_id, mission)}",
                                "relax the conflicting filter or choose a target "
                                "that satisfies it; a mission whose target fails "
                                "its own filters cannot pass both "
                                "target_in_top_k and hard_filters_hold",
                            ),
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
                            explain(
                                f"filters.attributes names {key!r}, which the "
                                f"target does not carry",
                                _nearest_keys(cursor, product_id, key),
                            ),
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
    if near:
        return f"did you mean one of {near}?"
    return f"use one of the keys the target carries: {sorted(keys)}"


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
            "run. Lab targets are unvalidated against the cluster."
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

    print(f"lab contract gate: {len(report.passed)} check(s) passed")
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
