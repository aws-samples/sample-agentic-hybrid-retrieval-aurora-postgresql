#!/usr/bin/env python3
"""Measure the served Mosaic retrieval path against an independent relevance corpus.

`data/evals/independent_relevance_queries.jsonl` ("IRC") is deliberately a
**separate** corpus from `data/evals/canonical_queries.jsonl` (the release
scorecard, `scripts/score_evals.py`) and from `data/evals/esci_judged_subset.json`
(the RRF-`k` tuning sweep, `scripts/evaluate_esci_k.py`). Its purpose is narrower
than either: establish graded relevance judgments from *catalog and evidence
grounding*, independent of any ranking the service has ever produced, and use
them to surface coverage gaps that the canonical 21-query teaching set and the
generated 720-case filter corpus do not probe.

Why a new corpus, and why it is not the ESCI subset or a fresh catalog crawl
--------------------------------------------------------------------------
- The 21-query canonical set is a teaching fixture: every query maps to a lab
  mission, and its judgments are pinned to prevent the release gate from
  drifting. Reusing its queries here would test nothing independent.
- `esci_judged_subset.json`'s 141 queries have already been fully spent on
  tuning: `scripts/evaluate_esci_k.py` computed the RRF-`k` sweep over every one
  of them, and `db/config/retrieval.yaml`'s `rrf_k: 60` reflects that sweep.
  Scoring final relevance quality on the same queries used to pick a retrieval
  parameter is optimistic by construction, so this corpus does not reuse them.
- This checkout has no Bedrock access and no `DATABASE_URL`, and the raw ESCI
  `examples.parquet` is intentionally not vendored in this repository; see
  `scripts/prepare_esci_judged_subset.py`. A fresh, larger ESCI slice cannot be
  produced from inside this environment. See "Held-out ESCI corpus" below for
  how this module stays ready to score one once a maintainer builds it.

Judged-item universe overlaps with existing anchors, disclosed, not hidden
----------------------------------------------------------------------------
`data/evals/real_catalog_lab_products.json` carries **unmodified source fields**
for 12 real `reviews-2023-500k-v1` products, and this corpus's judgments are
built from that file. Seven of those twelve products are already judged
somewhere in `canonical_queries.jsonl`, and four of those seven are the actual
target products of a live lab mission (`data/evals/mosaic_labs_missions.json`'s
`target_product_ids`). Every judgment therefore carries `"anchor_overlap"`:

- `"mission"`: the product is a live mission's own `target_product_ids` --
  1208825, 1277987, 1408222.
- `"canonical"`: the product is judged in `canonical_queries.jsonl` but is not
  itself a mission target -- 1138035, 1162128, 1168700.
- `"none"`: the product is outside both -- 1248512, 1379290, 1389794, 1481815,
  1490476.

A query whose only relevant judgments sit on `"mission"`/`"canonical"`
products is not independent evidence about this repository's retrieval
quality: it can pass by construction, because those products were selected
*because* they already rank well for a related query. The `anchor_free`
relevance tier below scores only the `"none"` subset, so a cohort resting on
overlapping products is visibly, separately weaker rather than blended into
one optimistic number. See `docs/evaluation-plan.md`'s "Coverage design"
section for the full disclosure and per-cohort counts.

Judgment status vocabulary, and what a relevance claim requires
--------------------------------------------------------------------
Every judgment in this corpus was authored by an automated session, not by a
human or an independent second party. Calling that "reviewed" would misstate
its provenance, so the vocabulary is:

- `"agent_grounded"`: quote- or paraphrase-traceable to a fact in
  `real_catalog_lab_products.json`. Grounded, not reviewed -- an automated
  session, not a person, drew the conclusion.
- `"agent_inferred"`: depends on something this checkout cannot verify
  offline -- current Aurora-served price or stock state, or a brand-tier/price
  inference rather than a quoted catalog fact.
- `"reviewed"`: reserved for a status a human or an independent second party
  actually sets. The validator requires non-empty `"reviewed_by"` and
  `"reviewed_on"` fields on any judgment claiming this status. No judgment in
  the committed corpus carries it today.
- `"esci_human"`: a human-labelled judgment carried over from the Amazon ESCI
  Shopping Queries Dataset (Apache-2.0), for the held-out corpus described
  below. Distinct from `"reviewed"` because the reviewer is ESCI's original
  annotation process, not a review of this project's own retrieval output.

**A relevance claim requires both a measured Aurora run and a `certified`
judgment** (`"reviewed"` or `"esci_human"`). The `certified` tier is empty for
today's committed corpus -- there are zero queries with a `"reviewed"` or
`"esci_human"` grade-2-or-3 judgment -- across all six request shapes, not just
some. `agent_grounded_only` (status `"agent_grounded"` only) is a useful
diagnostic of which cohorts rest on directly-quoted facts versus inference, but
it is agent-authored and does not by itself support a relevance claim.

Coverage design and why 24 queries, not more or fewer
-------------------------------------------------------
This is a coverage probe, not a statistically powered benchmark. The corpus
crosses 4 catalog cohorts (`headphones`, `monitor`, `chair`, and `general` for
genuinely cross-category requests) with 6 request-shape cohorts
(`semantic_intent`, `ambiguous_language`, `typo_or_exact_identity`,
`selective_filters`, `competing_preferences`, `unsatisfiable`), one query per
cell, for exactly 4 x 6 = 24 queries. Per-cohort N is 4 or 6 depending on which
axis is aggregated -- too small for a confidence interval, and this module
computes none. Growing this corpus should add cells (a new intent shape, a new
catalog cohort, or a second reviewed query per cell once a human reviewer or
Bedrock/Aurora access exists) rather than duplicating existing cells for a
larger N with no new coverage.

No-relevant-item and incomplete-judgment treatment
-----------------------------------------------------
A query is `unsatisfiable` when `expect_no_relevant_results` is `true`: nothing
in the reviewed catalog evidence satisfies it, so Recall/MRR/nDCG are
mathematically undefined (there is no relevant item to rank) and are never
computed for it. Instead it is scored on whether the service's own hard
negatives (declared, catalog-grounded near-misses) leaked into the returned
window, and on its result count. A query that is *not* marked unsatisfiable but
carries no judgment graded 2 or 3 under a given tier is excluded from that
tier's own denominator and named in it; a query with no grade-2-or-3 judgment
under *any* tier is a `judgment_gap`, printed by name under
`denominator.judgment_gap_query_ids`, never silently folded into "0 relevant
found".

Reused production machinery
------------------------------
This module never reimplements retrieval. `run_queries` calls
`service.retrieval.get_retrieval_service().search()`, the same entry point
`scripts/score_evals.py` measures the canonical scorecard through, and reads
rank from each result's own `signals.final_rank` exactly as
`scripts/score_evals.py` does -- never from list position, which the service
does not guarantee is contiguous once results are filtered downstream. Filter
and target-existence validation reuses `scripts.run_eval.validate_query_contract`
and `require_single_served_catalog` unchanged. Recall/MRR/nDCG arithmetic
reuses `scripts.evaluate.evaluate` unchanged. Retry-on-transient-connection-
failure reuses `scripts.score_evals.search_with_db_retry` unchanged.

Held-out ESCI corpus (not generated by this module)
-------------------------------------------------------
A maintainer holding the ESCI `examples.parquet` locally, and working against
the `reviews-2023-v2` catalog (which admits more judged queries than the 141
already spent on tuning), can build a second, disjoint corpus this runner is
already able to score. Its file contract:

- Same shape as `independent_relevance_queries.jsonl` (see
  `REQUIRED_QUERY_FIELDS`), scored with the same
  `--queries data/evals/esci_held_out_queries.jsonl` flag.
- Each judgment: `"status": "esci_human"`, `"grade"` mapped from the ESCI label
  via `esci_grade()` (E=3, S=2, C=1, I=0), `"source": "esci"`, `"license":
  "Apache-2.0"`, and `"anchor_overlap"` computed the same way as every other
  judgment (almost always `"none"`, since ESCI-judged products are not drawn
  from the mission/canonical anchor set).
- Each **record** additionally carries `"esci_query_id"`: the raw integer
  query id from the ESCI source dataset, distinct from this corpus's own
  namespaced `"query_id"` (for example `"ESCI-HELDOUT-9001"`).
- Before scoring, run `require_disjoint_from_tuning_sources(records)` (this
  module) against the loaded records: it fails loudly if any
  `"esci_query_id"` was already spent by `esci_judged_subset.json`'s 141
  tuning queries, or if any `"query_id"` collides with the canonical
  scorecard's `G-*` ids.

This module does not fetch, license-check, or generate that file -- doing so
needs the parquet file and Aurora/Bedrock access this checkout does not have.
`tests/test_independent_relevance_eval.py` proves the disjointness check and
the label-to-grade mapping against small synthetic fixtures, never against
real ESCI data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.evaluate import evaluate
from scripts.run_eval import require_single_served_catalog, validate_query_contract
from scripts.score_evals import search_with_db_retry
from service.config import get_settings
from service.db import connect
from service.models import SearchFilters, SearchRequest
from service.retrieval import get_retrieval_service
from service.retrieval_fingerprint import compute_retrieval_fingerprint

DEFAULT_QUERIES_PATH = REPO / "data" / "evals" / "independent_relevance_queries.jsonl"
DEFAULT_OUTPUT_PATH = (
    REPO / "benchmarks" / "results" / "independent_relevance_report.json"
)
CANONICAL_QUERIES_PATH = REPO / "data" / "evals" / "canonical_queries.jsonl"
MISSION_CONTRACT_PATH = REPO / "data" / "evals" / "mosaic_labs_missions.json"
ESCI_SUBSET_PATH = REPO / "data" / "evals" / "esci_judged_subset.json"
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0)

#: "agent_grounded"/"agent_inferred" are agent-authored; "reviewed" is reserved
#: for a human or independent second party (requires reviewed_by/reviewed_on);
#: "esci_human" is a human label carried over from a licensed third-party
#: dataset. See the module docstring for the full definition of each.
JUDGMENT_STATUSES = {"agent_grounded", "agent_inferred", "reviewed", "esci_human"}
#: "mission": the product is a live lab's own target. "canonical": judged in
#: canonical_queries.jsonl but not a mission target. "none": neither -- the
#: only products this corpus's evidence is independent of existing anchors on.
ANCHOR_OVERLAP_VALUES = {"mission", "canonical", "none"}
VALID_GRADES = {0, 1, 2, 3}
#: The six request shapes the agent-authored coverage probe must span.
REQUEST_SHAPES = {
    "semantic_intent",
    "ambiguous_language",
    "typo_or_exact_identity",
    "selective_filters",
    "competing_preferences",
    "unsatisfiable",
}
#: Held-out ESCI shopping queries carry human labels but no request-shape
#: classification; they are reported as their own cohort, never folded into
#: the six agent-authored shapes.
COHORT_INTENTS = REQUEST_SHAPES | {"esci_shopping_query"}
REQUIRED_QUERY_FIELDS = (
    "query_id",
    "query",
    "dataset_id",
    "cohort_category",
    "cohort_intent",
    "filters",
    "expect_no_relevant_results",
    "judgments",
    "hard_negative_ids",
)
#: ESCI relevance labels mapped to this corpus's 0-3 grade scale. Distinct from
#: `scripts.evaluate_esci_k.GAINS` (continuous nDCG gains for RRF-`k` tuning);
#: the two serve different purposes and must not be conflated.
ESCI_LABEL_TO_GRADE: dict[str, int] = {"E": 3, "S": 2, "C": 1, "I": 0}


def explain(found: str, fix: str) -> str:
    """Match the house error style: name the value found, then the fix."""
    return f"found {found}; fix: {fix}"


def esci_grade(label: str) -> int:
    """Map one ESCI relevance label to this corpus's 0-3 grade scale."""
    try:
        return ESCI_LABEL_TO_GRADE[label]
    except KeyError as error:
        raise ValueError(
            "Unknown ESCI label: "
            + explain(f"{label!r}", f"use one of {sorted(ESCI_LABEL_TO_GRADE)}")
        ) from error


def _relative_to_repo(path: Path) -> Path:
    """Report a path relative to the repo root, or absolute outside of it.

    A committed report always shows a repo-relative path. Tests pass a
    `tmp_path` corpus that never lives under `REPO`; falling back to the
    absolute path there keeps this reusable for both without raising.
    """
    try:
        return path.resolve().relative_to(REPO)
    except ValueError:
        return path.resolve()


def _mission_anchor_product_ids(path: Path = MISSION_CONTRACT_PATH) -> set[int]:
    """Every product id a live lab mission names as its own target."""
    contract = json.loads(path.read_text(encoding="utf-8"))
    ids: set[int] = set()
    for item in contract["missions"] + contract.get("supporting_checks", []):
        ids.update(item.get("target_product_ids") or [])
    return ids


def _canonical_judged_product_ids(path: Path = CANONICAL_QUERIES_PATH) -> set[int]:
    """Every product id judged anywhere in the canonical release scorecard."""
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for judgment in record.get("judgments", []):
            ids.add(judgment["product_id"])
    return ids


def compute_anchor_overlap(
    product_id: int,
    *,
    mission_ids: set[int],
    canonical_ids: set[int],
) -> str:
    """Classify one product against the two existing-anchor sources.

    `mission_ids` takes priority: a mission target is always also judged in
    canonical_queries.jsonl (the mission's canonical_query_id resolves through
    it), so checking canonical first would misreport a mission anchor as merely
    "canonical".
    """
    if product_id in mission_ids:
        return "mission"
    if product_id in canonical_ids:
        return "canonical"
    return "none"


def _validate_judgment(
    query_id: str,
    judgment: dict[str, Any],
    *,
    mission_ids: set[int],
    canonical_ids: set[int],
) -> None:
    product_id = judgment.get("product_id")
    grade = judgment.get("grade")
    status = judgment.get("status")
    if not isinstance(product_id, int):
        raise TypeError(
            f"{query_id} judgment has a non-integer product_id: "
            + explain(f"{product_id!r}", "use an integer catalog product_id")
        )
    if grade not in VALID_GRADES:
        raise ValueError(
            f"{query_id}/{product_id} has an invalid grade: "
            + explain(f"{grade!r}", f"use one of {sorted(VALID_GRADES)}")
        )
    if status not in JUDGMENT_STATUSES:
        raise ValueError(
            f"{query_id}/{product_id} has an invalid judgment status: "
            + explain(f"{status!r}", f"use one of {sorted(JUDGMENT_STATUSES)}")
        )
    if status == "reviewed" and not (
        judgment.get("reviewed_by") and judgment.get("reviewed_on")
    ):
        raise ValueError(
            f"{query_id}/{product_id} claims status 'reviewed' without review provenance: "
            + explain(
                f"reviewed_by={judgment.get('reviewed_by')!r}, "
                f"reviewed_on={judgment.get('reviewed_on')!r}",
                "set both reviewed_by and reviewed_on, or use 'agent_grounded'/"
                "'agent_inferred' if no human reviewed this judgment",
            )
        )
    if not judgment.get("rationale"):
        raise ValueError(
            f"{query_id}/{product_id} is missing a rationale: "
            + explain("empty rationale", "cite the catalog fact or mark the inference")
        )
    expected_overlap = compute_anchor_overlap(
        product_id, mission_ids=mission_ids, canonical_ids=canonical_ids
    )
    actual_overlap = judgment.get("anchor_overlap")
    if actual_overlap != expected_overlap:
        raise ValueError(
            f"{query_id}/{product_id} has anchor_overlap {actual_overlap!r}: "
            + explain(
                f"the mission/canonical cross-reference computes {expected_overlap!r}",
                f"set anchor_overlap to {expected_overlap!r}",
            )
        )


def _validate_hard_negatives(
    query_id: str, grades: dict[int, int], hard_negative_ids: list[int]
) -> None:
    for product_id in hard_negative_ids:
        if product_id not in grades:
            raise ValueError(
                f"{query_id} hard_negative_ids references an unjudged product: "
                + explain(f"product_id {product_id}", "add a grade-0 judgment for it")
            )
        if grades[product_id] != 0:
            raise ValueError(
                f"{query_id} hard_negative_ids references a non-zero judgment: "
                + explain(
                    f"product_id {product_id} graded {grades[product_id]}",
                    "hard negatives must be graded 0",
                )
            )


def _validate_record(
    record: dict[str, Any],
    *,
    mission_ids: set[int],
    canonical_ids: set[int],
) -> None:
    missing = [
        field_name for field_name in REQUIRED_QUERY_FIELDS if field_name not in record
    ]
    if missing:
        raise ValueError(
            f"{record.get('query_id', '<missing>')} is missing required fields: "
            + explain(f"{missing}", f"add {missing} to the record")
        )
    query_id = record["query_id"]
    if record["cohort_intent"] not in COHORT_INTENTS:
        raise ValueError(
            f"{query_id} has an unknown cohort_intent: "
            + explain(
                f"{record['cohort_intent']!r}", f"use one of {sorted(COHORT_INTENTS)}"
            )
        )
    if not isinstance(record["filters"], dict):
        raise TypeError(
            f"{query_id} filters must be a JSON object: "
            + explain(f"{record['filters']!r}", "use {} for an unconstrained query")
        )
    judgments = record["judgments"]
    if not isinstance(judgments, list):
        raise TypeError(
            f"{query_id} judgments must be a list: "
            + explain(f"{judgments!r}", "use [] for an unsatisfiable query")
        )
    for judgment in judgments:
        _validate_judgment(
            query_id, judgment, mission_ids=mission_ids, canonical_ids=canonical_ids
        )
    product_ids = [judgment["product_id"] for judgment in judgments]
    if len(set(product_ids)) != len(product_ids):
        raise ValueError(
            f"{query_id} judges the same product twice: "
            + explain(f"{product_ids}", "keep exactly one judgment per product_id")
        )
    grades = {judgment["product_id"]: judgment["grade"] for judgment in judgments}
    _validate_hard_negatives(query_id, grades, record["hard_negative_ids"])
    has_relevant = any(grade >= 2 for grade in grades.values())
    if record["expect_no_relevant_results"] and has_relevant:
        raise ValueError(
            f"{query_id} is marked unsatisfiable but carries a relevant judgment: "
            + explain(
                f"grades {grades}", "either remove the grade>=2 judgment or the flag"
            )
        )


def load_independent_relevance_queries(path: Path) -> list[dict[str, Any]]:
    """Load and structurally validate an independent relevance corpus.

    Raises `ValueError`/`TypeError` on any malformed record, duplicate
    `query_id`, an out-of-vocabulary judgment status or cohort, a hard negative
    that is not itself a grade-0 judgment, a `"reviewed"` judgment missing its
    review provenance, or an `"anchor_overlap"` that disagrees with a fresh
    cross-reference against `canonical_queries.jsonl` and
    `mosaic_labs_missions.json`. This never checks live Aurora eligibility --
    `validate_query_contract` (reused from `scripts.run_eval`) does that.
    """
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(
            "Independent relevance corpus is empty: "
            + explain(f"{path}", "add at least one query record")
        )
    mission_ids = _mission_anchor_product_ids()
    canonical_ids = _canonical_judged_product_ids()
    seen: set[str] = set()
    for record in records:
        _validate_record(record, mission_ids=mission_ids, canonical_ids=canonical_ids)
        query_id = record["query_id"]
        if query_id in seen:
            raise ValueError(
                "Duplicate independent relevance query_id: "
                + explain(f"{query_id!r}", "give every query a unique query_id")
            )
        seen.add(query_id)
    return records


def tuning_source_query_id_overlap(
    records: list[dict[str, Any]],
    *,
    esci_subset_path: Path = ESCI_SUBSET_PATH,
    canonical_path: Path = CANONICAL_QUERIES_PATH,
) -> dict[str, list[Any]]:
    """Identify which held-out records reuse a tuning or canonical query id.

    Checks each record's `esci_query_id` (the ESCI source dataset's own raw id)
    against `esci_judged_subset.json`'s 141 tuning ids, and each record's own
    `query_id` against the canonical scorecard's `G-*` ids. Both fields are
    checked because they live in different namespaces; comparing only one would
    miss the collision the other is meant to catch.
    """
    esci_subset = json.loads(esci_subset_path.read_text(encoding="utf-8"))
    tuning_ids = {case["query_id"] for case in esci_subset["queries"]}
    canonical_ids = {
        json.loads(line)["query_id"]
        for line in canonical_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    tuning_conflicts = []
    canonical_conflicts = []
    for record in records:
        if "esci_query_id" not in record:
            raise ValueError(
                f"{record.get('query_id', '<missing>')} is missing esci_query_id: "
                + explain(
                    "no esci_query_id field",
                    "add the ESCI source dataset's raw integer query id",
                )
            )
        if record["esci_query_id"] in tuning_ids:
            tuning_conflicts.append(record["esci_query_id"])
        if record["query_id"] in canonical_ids:
            canonical_conflicts.append(record["query_id"])
    return {
        "esci_tuning_set": tuning_conflicts,
        "canonical_scorecard": canonical_conflicts,
    }


def require_disjoint_from_tuning_sources(
    records: list[dict[str, Any]],
    **kwargs: Any,
) -> None:
    """Raise if a held-out corpus reuses an ESCI-tuning or canonical query id."""
    overlap = tuning_source_query_id_overlap(records, **kwargs)
    conflicts = {source: ids for source, ids in overlap.items() if ids}
    if conflicts:
        raise ValueError(
            "Held-out corpus query ids collide with a source already spent on "
            "tuning or release gating: "
            + explain(
                f"{conflicts}", "pick different query ids for the held-out corpus"
            )
        )


#: Each tier answers a different question about the same 24 queries:
#: `all_inclusive` is every judgment regardless of provenance; `agent_grounded_only`
#: isolates the agent's directly-quoted claims from its inferences;
#: `certified` is the only tier a relevance claim may cite (empty today -- see
#: the module docstring); `anchor_free` isolates products this corpus's
#: evidence is independent of existing lab/canonical anchors on.
TIER_PREDICATES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "all_inclusive": lambda judgment: True,
    "agent_grounded_only": lambda judgment: judgment["status"] == "agent_grounded",
    "certified": lambda judgment: judgment["status"] in {"reviewed", "esci_human"},
    "anchor_free": lambda judgment: judgment["anchor_overlap"] == "none",
}


@dataclass(frozen=True)
class QueryClassification:
    """Which relevance-metric tier(s), if any, each query participates in."""

    unsatisfiable: list[str] = field(default_factory=list)
    judgment_gap: list[str] = field(default_factory=list)
    answerable: dict[str, list[str]] = field(default_factory=dict)


def classify_queries(queries: list[dict[str, Any]]) -> QueryClassification:
    """Sort queries into metric tiers without ever inferring a judgment.

    A query is exactly one of: `unsatisfiable` (declared, scored separately),
    `judgment_gap` (not unsatisfiable, but no grade>=2 judgment exists under
    *any* tier -- excluded from every relevance metric), or answerable under
    one or more of `TIER_PREDICATES`. `answerable[tier]` for any tier is always
    a subset of `answerable["all_inclusive"]`.
    """
    classification = QueryClassification(
        answerable={tier: [] for tier in TIER_PREDICATES}
    )
    for query in queries:
        if query["expect_no_relevant_results"]:
            classification.unsatisfiable.append(query["query_id"])
            continue
        judgments = query["judgments"]
        if not any(judgment["grade"] >= 2 for judgment in judgments):
            classification.judgment_gap.append(query["query_id"])
            continue
        for tier, predicate in TIER_PREDICATES.items():
            if any(
                judgment["grade"] >= 2 and predicate(judgment) for judgment in judgments
            ):
                classification.answerable[tier].append(query["query_id"])
    return classification


@dataclass
class QueryOutcome:
    """One query's production search result, kept separate from its judgments.

    `ranked_product_ids` is `(final_rank, product_id)`, read from each result's
    own `signals.final_rank` -- never from list position -- exactly as
    `scripts/score_evals.py` builds its own ranked results.
    """

    query_id: str
    ranked_product_ids: list[tuple[int, int]]
    result_count: int
    search_event_id: str | None
    strategy: str | None
    latency_ms: float | None

    @property
    def result_ids(self) -> list[int]:
        """Product ids in final-rank order, for hard-negative window checks."""
        return [product_id for _, product_id in sorted(self.ranked_product_ids)]

    @property
    def rank_by_product(self) -> dict[int, int]:
        return {product_id: rank for rank, product_id in self.ranked_product_ids}


def _search_request(query: dict[str, Any], k: int) -> SearchRequest:
    return SearchRequest(
        query=query["query"],
        filters=SearchFilters.model_validate(query["filters"]),
        limit=k,
        include_diagnostics=True,
        rerank=True,
        session_id="independent-relevance-eval",
    )


def run_queries(
    queries: list[dict[str, Any]],
    retrieval: Any,
    *,
    k: int,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, QueryOutcome], list[dict[str, str]]]:
    """Run every query through production retrieval; never let one crash the rest.

    Returns `(outcomes, failures)`. A query that raises after the transient-
    connection retries in `search_with_db_retry` is recorded in `failures` with
    its error type and message, and is excluded from `outcomes` -- and
    therefore from every metric -- rather than aborting the whole report.
    """
    outcomes: dict[str, QueryOutcome] = {}
    failures: list[dict[str, str]] = []
    for query in queries:
        query_id = query["query_id"]
        try:
            response = search_with_db_retry(
                retrieval,
                _search_request(query, k),
                query_id=query_id,
                retry_delays=retry_delays,
                sleep=sleep,
            )
        except Exception as error:  # noqa: BLE001 - recorded in `failures`, never silenced
            failures.append(
                {
                    "query_id": query_id,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
            )
            continue
        outcomes[query_id] = QueryOutcome(
            query_id=query_id,
            ranked_product_ids=[
                (result.signals.final_rank, result.product_id)
                for result in response.results
                if result.signals is not None
            ],
            result_count=len(response.results),
            search_event_id=str(response.search_event_id),
            strategy=(response.diagnostics.strategy if response.diagnostics else None),
            latency_ms=(
                response.diagnostics.total_latency_ms if response.diagnostics else None
            ),
        )
    return outcomes, failures


def _ranked_from_outcomes(
    outcomes: dict[str, QueryOutcome],
    query_ids: list[str],
) -> dict[str, list[tuple[int, int]]]:
    return {
        query_id: outcomes[query_id].ranked_product_ids
        for query_id in query_ids
        if query_id in outcomes
    }


def _truth_for_queries(
    queries_by_id: dict[str, dict[str, Any]],
    query_ids: list[str],
    *,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, dict[int, int]]:
    truth: dict[str, dict[int, int]] = {}
    for query_id in query_ids:
        judgments = queries_by_id[query_id]["judgments"]
        truth[query_id] = {
            judgment["product_id"]: judgment["grade"]
            for judgment in judgments
            if predicate(judgment)
        }
    return truth


def _relevance_tier(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    query_ids: list[str],
    *,
    predicate: Callable[[dict[str, Any]], bool],
    k: int,
) -> dict[str, Any]:
    """Score one relevance tier over the queries that actually ran.

    Excludes queries missing an outcome (a recorded failure) from this tier's
    own denominator, reporting the exclusion by name rather than padding the
    tier with a manufactured zero score.
    """
    scored_ids = [query_id for query_id in query_ids if query_id in outcomes]
    excluded = sorted(set(query_ids) - set(scored_ids))
    if not scored_ids:
        return {
            "scored_query_count": 0,
            "excluded_due_to_failure": excluded,
            "metrics": None,
        }
    truth = _truth_for_queries(queries_by_id, scored_ids, predicate=predicate)
    ranked = _ranked_from_outcomes(outcomes, scored_ids)
    metrics = evaluate(truth, ranked, k)
    return {
        "scored_query_count": metrics["query_count"],
        "excluded_due_to_failure": excluded,
        "metrics": {
            f"recall@{k}": metrics[f"recall@{k}"],
            "mrr": metrics["mrr"],
            f"ndcg@{k}": metrics[f"ndcg@{k}"],
        },
        "per_query": metrics["per_query"],
    }


def _relevance_by_tier(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    classification: QueryClassification,
    *,
    k: int,
) -> dict[str, Any]:
    return {
        tier: _relevance_tier(
            queries_by_id,
            outcomes,
            classification.answerable[tier],
            predicate=predicate,
            k=k,
        )
        for tier, predicate in TIER_PREDICATES.items()
    }


def _hard_negative_violations(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
) -> list[dict[str, Any]]:
    """Report every query whose returned window contained a declared hard negative.

    Runs over every query with an outcome, not just the unsatisfiable cohort:
    an answerable query's hard negative leaking into the top-k is exactly as
    real a finding as an unsatisfiable query's. Ranks come from each result's
    own `final_rank`, not from list position.
    """
    violations = []
    for query_id, outcome in outcomes.items():
        hard_negatives = queries_by_id[query_id]["hard_negative_ids"]
        rank_by_product = outcome.rank_by_product
        leaked = [pid for pid in hard_negatives if pid in rank_by_product]
        if leaked:
            violations.append(
                {
                    "query_id": query_id,
                    "leaked_product_ids": leaked,
                    "ranks": [rank_by_product[pid] for pid in leaked],
                }
            )
    return violations


def _empty_result_behavior(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    classification: QueryClassification,
) -> dict[str, Any]:
    """Separate 'correctly returned nothing' from 'unexpectedly returned nothing'."""
    unsatisfiable_zero = unsatisfiable_nonzero_clean = unsatisfiable_violation = 0
    violation_ids = {
        v["query_id"] for v in _hard_negative_violations(queries_by_id, outcomes)
    }
    for query_id in classification.unsatisfiable:
        outcome = outcomes.get(query_id)
        if outcome is None:
            continue
        if outcome.result_count == 0:
            unsatisfiable_zero += 1
        elif query_id in violation_ids:
            unsatisfiable_violation += 1
        else:
            unsatisfiable_nonzero_clean += 1
    unexpected_empty = [
        query_id
        for query_id in classification.answerable["all_inclusive"]
        if query_id in outcomes and outcomes[query_id].result_count == 0
    ]
    return {
        "unsatisfiable_returned_zero_results": unsatisfiable_zero,
        "unsatisfiable_returned_nonzero_without_hard_negative": unsatisfiable_nonzero_clean,
        "unsatisfiable_returned_hard_negative": unsatisfiable_violation,
        "answerable_unexpected_empty_results": unexpected_empty,
    }


def _latency_summary(
    outcomes: dict[str, QueryOutcome], query_ids: Sequence[str]
) -> dict[str, Any]:
    samples = sorted(
        outcomes[query_id].latency_ms
        for query_id in query_ids
        if query_id in outcomes and outcomes[query_id].latency_ms is not None
    )
    if not samples:
        return {"sample_count": 0, "mean_ms": None, "median_ms": None, "p95_ms": None}
    p95_index = min(len(samples) - 1, round(0.95 * (len(samples) - 1)))
    return {
        "sample_count": len(samples),
        "mean_ms": round(statistics.fmean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[p95_index], 3),
    }


def _cohort_breakdown(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    classification: QueryClassification,
    *,
    dimension: str,
    k: int,
) -> dict[str, Any]:
    """Per-cohort relevance (every tier), violations, and latency."""
    cohorts = sorted({query[dimension] for query in queries_by_id.values()})
    breakdown: dict[str, Any] = {}
    for cohort in cohorts:
        cohort_query_ids = {
            query_id
            for query_id, query in queries_by_id.items()
            if query[dimension] == cohort
        }
        cohort_classification = QueryClassification(
            unsatisfiable=[
                q for q in classification.unsatisfiable if q in cohort_query_ids
            ],
            judgment_gap=[
                q for q in classification.judgment_gap if q in cohort_query_ids
            ],
            answerable={
                tier: [q for q in ids if q in cohort_query_ids]
                for tier, ids in classification.answerable.items()
            },
        )
        breakdown[cohort] = {
            "query_count": len(cohort_query_ids),
            "unsatisfiable_query_count": len(cohort_classification.unsatisfiable),
            "judgment_gap_query_count": len(cohort_classification.judgment_gap),
            "relevance": _relevance_by_tier(
                queries_by_id, outcomes, cohort_classification, k=k
            ),
            "hard_negative_violations": len(
                [
                    v
                    for v in _hard_negative_violations(queries_by_id, outcomes)
                    if v["query_id"] in cohort_query_ids
                ]
            ),
            "latency": _latency_summary(outcomes, sorted(cohort_query_ids)),
        }
    return breakdown


def build_report(
    queries: list[dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    failures: list[dict[str, str]],
    *,
    k: int,
    queries_path: Path,
) -> dict[str, Any]:
    """Assemble the full report: provenance, tiered relevance, and separated
    eligibility, empty-result, failure, and latency sections.
    """
    queries_by_id = {query["query_id"]: query for query in queries}
    classification = classify_queries(queries)
    settings = get_settings()
    return {
        "corpus": {
            "path": str(_relative_to_repo(queries_path)),
            "query_count": len(queries),
            "query_set_sha256": hashlib.sha256(queries_path.read_bytes()).hexdigest(),
            "coverage": {
                "cohort_category": sorted({q["cohort_category"] for q in queries}),
                "cohort_intent": sorted({q["cohort_intent"] for q in queries}),
            },
        },
        "denominator": {
            "queries_attempted": len(queries),
            "queries_failed": len(failures),
            "unsatisfiable_query_count": len(classification.unsatisfiable),
            "judgment_gap_query_count": len(classification.judgment_gap),
            "judgment_gap_query_ids": classification.judgment_gap,
            "answerable_query_counts": {
                tier: len(ids) for tier, ids in classification.answerable.items()
            },
        },
        "failures": failures,
        "relevance": _relevance_by_tier(queries_by_id, outcomes, classification, k=k),
        "eligibility_violations": _hard_negative_violations(queries_by_id, outcomes),
        "empty_result_behavior": _empty_result_behavior(
            queries_by_id, outcomes, classification
        ),
        "latency": _latency_summary(outcomes, list(outcomes)),
        "by_cohort_category": _cohort_breakdown(
            queries_by_id, outcomes, classification, dimension="cohort_category", k=k
        ),
        "by_cohort_intent": _cohort_breakdown(
            queries_by_id, outcomes, classification, dimension="cohort_intent", k=k
        ),
        "k": k,
        "models": {
            "embedding": settings.embedding_model_id,
            "rerank": settings.rerank_model_id,
        },
        "source": {
            "revision": settings.source_revision,
            "worktree_dirty": settings.source_worktree_dirty,
        },
        "dataset_manifest_sha256": settings.dataset_manifest_sha256,
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "instance_class": settings.aurora_instance_class,
        },
        "retrieval_fingerprint": compute_retrieval_fingerprint(),
        "measured_at": datetime.now(UTC).isoformat(),
    }


def _load_and_validate_against_aurora(queries_path: Path) -> list[dict[str, Any]]:
    """Structural validation, then live filter/target-eligibility validation.

    Shared by `--validate-only` and `measure` so both fail on exactly the same
    conditions, before any model call.
    """
    queries = load_independent_relevance_queries(queries_path)
    require_single_served_catalog(queries)
    with connect() as connection:
        validate_query_contract(connection, queries)
    return queries


def measure(queries_path: Path, *, k: int) -> dict[str, Any]:
    """Load, validate, run, and score the independent relevance corpus.

    This is the function a maintainer runs against Aurora; see the module's
    `__main__` block for its CLI. It reuses `validate_query_contract` and
    `require_single_served_catalog` unchanged, so a target that does not exist
    or a positive judgment that violates the query's own filters fails here,
    before any model call, exactly as it does for the canonical scorecard.
    """
    queries = _load_and_validate_against_aurora(queries_path)
    retrieval = get_retrieval_service()
    outcomes, failures = run_queries(queries, retrieval, k=k)
    return build_report(queries, outcomes, failures, k=k, queries_path=queries_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Load and validate the corpus (schema + live eligibility) without "
        "spending embedding or reranking calls.",
    )
    args = parser.parse_args()
    if args.validate_only:
        queries = _load_and_validate_against_aurora(args.queries)
        print(f"Independent relevance corpus valid: {len(queries)} queries.")
        return
    report = measure(args.queries, k=args.k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output}")
    print(
        json.dumps(
            {
                "denominator": report["denominator"],
                "relevance": report["relevance"],
                "eligibility_violations": len(report["eligibility_violations"]),
                "empty_result_behavior": report["empty_result_behavior"],
                "latency": report["latency"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
