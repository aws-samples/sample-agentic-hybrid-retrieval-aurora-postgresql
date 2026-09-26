#!/usr/bin/env python3
"""Measure the served Mosaic retrieval path against an independent relevance corpus.

`data/evals/independent_relevance_queries.jsonl` ("IRC") is deliberately a
**separate** corpus from `data/evals/canonical_queries.jsonl` (the release
scorecard, `scripts/score_evals.py`) and from `data/evals/esci_judged_subset.json`
(the RRF-`k` tuning sweep, `scripts/evaluate_esci_k.py`). Its purpose is narrower
than either: establish graded relevance judgments from *catalog and evidence
review*, independent of any ranking the service has ever produced, and use them
to surface coverage gaps that the canonical 21-query teaching set and the
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
- This checkout has no Bedrock access and no `DATABASE_URL` (see the module
  docstring in `scripts/run_eval.py` for what that means for query validation),
  and the raw ESCI `examples.parquet` is intentionally not vendored in this
  repository (`NOTICE.md`-tracked license terms; see
  `scripts/prepare_esci_judged_subset.py`). A fresh, larger ESCI slice cannot be
  produced from inside this environment.

What was available instead, and how it was used
-------------------------------------------------
`data/evals/real_catalog_lab_products.json` carries **unmodified source fields**
(title, feature text, attributes) for 12 real `reviews-2023-500k-v1` products.
Cross-referencing it against `canonical_queries.jsonl` and `canonical_scorecard`
finds five of those twelve products -- 1248512, 1379290, 1389794, 1408222's
sibling 1481815, and 1490476 -- **never referenced by the canonical scorecard**.
Every judgment in this corpus is either grounded in a quoted or paraphrased
fact from that source file (`"status": "reviewed"`), or explicitly marked
`"status": "provisional"` when the grade depends on something this checkout
cannot verify offline: current Aurora-served price or stock state, or a
brand-tier/price inference rather than a quoted catalog fact. See
`docs/evaluation-plan.md` for the full status vocabulary and what a relevance
claim requires.

Coverage design and why 24 queries, not more or fewer
-------------------------------------------------------
This is a coverage probe, not a statistically powered benchmark. The corpus
crosses 4 catalog cohorts (`headphones`, `monitor`, `chair`, and `general` for
genuinely cross-category requests) with 6 request-shape cohorts
(`semantic_intent`, `ambiguous_language`, `typo_or_exact_identity`,
`selective_filters`, `competing_preferences`, `unsatisfiable`), one query per
cell, for exactly 4 x 6 = 24 queries. Per-cohort N is 4 or 6 depending on which
axis is aggregated -- too small for a confidence interval, and this module
computes none. The report states point metrics per cohort and nothing implying
statistical significance. Growing this corpus should add cells (a new intent
shape, a new catalog cohort, or -- once Aurora and Bedrock access exist -- a
second reviewed query per cell) rather than duplicating existing cells for a
larger N with no new coverage.

No-relevant-item and incomplete-judgment treatment
-----------------------------------------------------
A query is `unsatisfiable` when `expect_no_relevant_results` is `true`: nothing
in the reviewed catalog evidence satisfies it, so Recall/MRR/nDCG are
mathematically undefined (there is no relevant item to rank) and are never
computed for it. Instead it is scored on whether the service's own hard
negatives (declared, catalog-grounded near-misses) leaked into the returned
window, and on its result count. A query that is *not* marked unsatisfiable but
carries no judgment graded 2 or 3 is a `judgment_gap`: the corpus does not yet
have enough review to score it, and it is excluded from every relevance metric
with its own visible count in the report, never silently folded into "0
relevant found". `queries_scored` and `queries_excluded` (with per-query
reasons) are both always printed, so a shrinking denominator is never hidden.

Two relevance tiers are reported side by side: `all_inclusive` uses every
judgment regardless of status, and `reviewed_only` uses only `"status":
"reviewed"` judgments (a query missing a reviewed grade-2-or-3 judgment is
excluded from that tier specifically). Per `docs/evaluation-plan.md`, only the
`reviewed_only` tier -- measured against Aurora -- supports a relevance claim.

Reused production machinery
------------------------------
This module never reimplements retrieval. `run_queries` calls
`service.retrieval.get_retrieval_service().search()`, the same entry point
`scripts/score_evals.py` measures the canonical scorecard through. Filter and
target-existence validation reuses `scripts.run_eval.validate_query_contract`
and `require_single_served_catalog` unchanged. Recall/MRR/nDCG arithmetic
reuses `scripts.evaluate.evaluate` unchanged. Retry-on-transient-connection-
failure reuses `scripts.score_evals.search_with_db_retry` unchanged.
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
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0)

JUDGMENT_STATUSES = {"reviewed", "provisional"}
VALID_GRADES = {0, 1, 2, 3}
COHORT_INTENTS = {
    "semantic_intent",
    "ambiguous_language",
    "typo_or_exact_identity",
    "selective_filters",
    "competing_preferences",
    "unsatisfiable",
}
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


def explain(found: str, fix: str) -> str:
    """Match the house error style: name the value found, then the fix."""
    return f"found {found}; fix: {fix}"


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


def _validate_judgment(query_id: str, judgment: dict[str, Any]) -> None:
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
    if not judgment.get("rationale"):
        raise ValueError(
            f"{query_id}/{product_id} is missing a rationale: "
            + explain("empty rationale", "cite the catalog fact or mark the inference")
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


def _validate_record(record: dict[str, Any]) -> None:
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
        _validate_judgment(query_id, judgment)
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
    """Load and structurally validate the independent relevance corpus.

    Raises `ValueError` on any malformed record, duplicate `query_id`, an
    out-of-vocabulary judgment status or cohort, or a hard negative that is not
    itself a grade-0 judgment. This never checks live Aurora eligibility --
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
    seen: set[str] = set()
    for record in records:
        _validate_record(record)
        query_id = record["query_id"]
        if query_id in seen:
            raise ValueError(
                "Duplicate independent relevance query_id: "
                + explain(f"{query_id!r}", "give every query a unique query_id")
            )
        seen.add(query_id)
    return records


@dataclass(frozen=True)
class QueryClassification:
    """Which relevance-metric tier, if any, each query participates in."""

    unsatisfiable: list[str] = field(default_factory=list)
    answerable_all: list[str] = field(default_factory=list)
    answerable_reviewed: list[str] = field(default_factory=list)
    judgment_gap: list[str] = field(default_factory=list)


def classify_queries(queries: list[dict[str, Any]]) -> QueryClassification:
    """Sort queries into metric tiers without ever inferring a judgment.

    A query is exactly one of: `unsatisfiable` (declared, scored separately),
    `judgment_gap` (not unsatisfiable, but no grade>=2 judgment exists yet --
    excluded from every relevance metric), or answerable under one or both
    relevance tiers. `answerable_reviewed` is always a subset of
    `answerable_all`.
    """
    classification = QueryClassification()
    for query in queries:
        if query["expect_no_relevant_results"]:
            classification.unsatisfiable.append(query["query_id"])
            continue
        grades_all = {j["product_id"]: j["grade"] for j in query["judgments"]}
        grades_reviewed = {
            j["product_id"]: j["grade"]
            for j in query["judgments"]
            if j["status"] == "reviewed"
        }
        has_relevant_all = any(grade >= 2 for grade in grades_all.values())
        has_relevant_reviewed = any(grade >= 2 for grade in grades_reviewed.values())
        if not has_relevant_all:
            classification.judgment_gap.append(query["query_id"])
            continue
        classification.answerable_all.append(query["query_id"])
        if has_relevant_reviewed:
            classification.answerable_reviewed.append(query["query_id"])
    return classification


@dataclass
class QueryOutcome:
    """One query's production search result, kept separate from its judgments."""

    query_id: str
    result_ids: list[int]
    result_count: int
    search_event_id: str | None
    strategy: str | None
    latency_ms: float | None


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
            result_ids=[result.product_id for result in response.results],
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
        query_id: list(enumerate(outcomes[query_id].result_ids, 1))
        for query_id in query_ids
        if query_id in outcomes
    }


def _truth_for_queries(
    queries_by_id: dict[str, dict[str, Any]],
    query_ids: list[str],
    *,
    reviewed_only: bool,
) -> dict[str, dict[int, int]]:
    truth: dict[str, dict[int, int]] = {}
    for query_id in query_ids:
        judgments = queries_by_id[query_id]["judgments"]
        truth[query_id] = {
            j["product_id"]: j["grade"]
            for j in judgments
            if not reviewed_only or j["status"] == "reviewed"
        }
    return truth


def _relevance_tier(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
    query_ids: list[str],
    *,
    reviewed_only: bool,
    k: int,
) -> dict[str, Any] | None:
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
    truth = _truth_for_queries(queries_by_id, scored_ids, reviewed_only=reviewed_only)
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


def _hard_negative_violations(
    queries_by_id: dict[str, dict[str, Any]],
    outcomes: dict[str, QueryOutcome],
) -> list[dict[str, Any]]:
    """Report every query whose returned window contained a declared hard negative.

    Runs over every query with an outcome, not just the unsatisfiable cohort:
    an answerable query's hard negative leaking into the top-k is exactly as
    real a finding as an unsatisfiable query's.
    """
    violations = []
    for query_id, outcome in outcomes.items():
        hard_negatives = queries_by_id[query_id]["hard_negative_ids"]
        leaked = [pid for pid in hard_negatives if pid in outcome.result_ids]
        if leaked:
            violations.append(
                {
                    "query_id": query_id,
                    "leaked_product_ids": leaked,
                    "ranks": [outcome.result_ids.index(pid) + 1 for pid in leaked],
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
        for query_id in classification.answerable_all
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
    """Per-cohort relevance, violations, and latency, keyed by `dimension`."""
    cohorts = sorted({query[dimension] for query in queries_by_id.values()})
    breakdown: dict[str, Any] = {}
    for cohort in cohorts:
        cohort_query_ids = [
            query_id
            for query_id, query in queries_by_id.items()
            if query[dimension] == cohort
        ]
        answerable_all = [
            q for q in classification.answerable_all if q in cohort_query_ids
        ]
        answerable_reviewed = [
            q for q in classification.answerable_reviewed if q in cohort_query_ids
        ]
        unsatisfiable = [
            q for q in classification.unsatisfiable if q in cohort_query_ids
        ]
        breakdown[cohort] = {
            "query_count": len(cohort_query_ids),
            "unsatisfiable_query_count": len(unsatisfiable),
            "judgment_gap_query_count": len(
                [q for q in classification.judgment_gap if q in cohort_query_ids]
            ),
            "all_inclusive": _relevance_tier(
                queries_by_id, outcomes, answerable_all, reviewed_only=False, k=k
            ),
            "reviewed_only": _relevance_tier(
                queries_by_id, outcomes, answerable_reviewed, reviewed_only=True, k=k
            ),
            "hard_negative_violations": len(
                [
                    v
                    for v in _hard_negative_violations(queries_by_id, outcomes)
                    if v["query_id"] in cohort_query_ids
                ]
            ),
            "latency": _latency_summary(outcomes, cohort_query_ids),
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
            "answerable_all_inclusive_query_count": len(classification.answerable_all),
            "answerable_reviewed_only_query_count": len(
                classification.answerable_reviewed
            ),
        },
        "failures": failures,
        "relevance": {
            "all_inclusive": _relevance_tier(
                queries_by_id,
                outcomes,
                classification.answerable_all,
                reviewed_only=False,
                k=k,
            ),
            "reviewed_only": _relevance_tier(
                queries_by_id,
                outcomes,
                classification.answerable_reviewed,
                reviewed_only=True,
                k=k,
            ),
        },
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
