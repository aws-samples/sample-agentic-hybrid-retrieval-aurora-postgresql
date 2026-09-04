#!/usr/bin/env python3
"""Measure the served Mosaic retrieval path against graded canonical judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.eval_contract import load_evaluation_queries
from scripts.evaluate import evaluate, load_judgments
from scripts.run_eval import validate_query_contract
from service.config import get_settings
from service.db import connect
from service.models import SearchFilters, SearchRequest
from service.retrieval import get_retrieval_service
from service.retrieval_fingerprint import (
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
    compute_scorecard_methodology_sha256,
)

PRODUCT_RETRIEVAL_SCOPE = "product_retrieval"
AGENT_CONTRACT_SCOPE = "agent_contract"
SCORECARD_DB_RETRY_DELAYS = (1.0, 2.0)
CANONICAL_SCORECARD_PATH = "data/evals/canonical_scorecard.json"
CANONICAL_RANKED_RESULTS_PATH = "data/evals/canonical_ranked_results.csv"
CANONICAL_STAGE_ABLATION_PATH = "data/evals/canonical_stage_ablation.json"
POST_MEASUREMENT_ARTIFACT_PATHS = {
    CANONICAL_SCORECARD_PATH,
    CANONICAL_RANKED_RESULTS_PATH,
    CANONICAL_STAGE_ABLATION_PATH,
}
RESULT_FIELDNAMES = (
    "query_id",
    "product_id",
    "rank",
    "search_event_id",
    "strategy",
    "total_latency_ms",
)
#: The committed subset: no search_event_id, no latency, no host or cluster
#: identity. See `_write_ranked_results`.
RANKED_RESULT_FIELDNAMES = ("query_id", "product_id", "rank")
RANKED_RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / CANONICAL_RANKED_RESULTS_PATH
)
FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")


def query_set_sha256(path: Path) -> str:
    """Return the identity of the judgments used to establish a scorecard."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_retrieval_queries(
    queries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep tool-orchestration cases out of single-request retrieval metrics."""
    scored: list[dict[str, Any]] = []
    excluded: list[str] = []
    for query in queries:
        scope = query.get("evaluation_scope", PRODUCT_RETRIEVAL_SCOPE)
        if scope == PRODUCT_RETRIEVAL_SCOPE:
            scored.append(query)
        elif scope == AGENT_CONTRACT_SCOPE:
            excluded.append(query["query_id"])
        else:
            raise ValueError(
                f"{query['query_id']} has evaluation_scope={scope!r}; expected "
                f"{PRODUCT_RETRIEVAL_SCOPE!r} or {AGENT_CONTRACT_SCOPE!r}. "
                "Fix the canonical evaluation scope before scoring."
            )
    if not scored:
        raise ValueError(
            "Canonical scorecard has no product_retrieval queries; mark at least "
            "one query with evaluation_scope='product_retrieval'."
        )
    return scored, excluded


#: Retrieval acronyms the mechanical transform below cannot recognize. Without
#: these, `rrf_and_reranking` renders as "Rrf and reranking" and
#: `eligibility_before_ann` as "Eligibility before ann", which reads as a name.
#: These labels exist to make internal identifiers legible to a participant, so
#: three of them rendering as typos defeats the purpose.
#:
#: This is a vocabulary, not a per-concept mapping: it holds only tokens that
#: appear in `data/evals/canonical_queries.jsonl` today, and an unrecognized
#: token still falls through to the mechanical rule. Adding a concept that uses
#: a new acronym is a one-line change here, and `test_score_evals.py` pins every
#: label the current query set produces, so a missing entry fails loudly rather
#: than shipping a lowercased acronym.
_CONCEPT_ACRONYMS = {"rrf": "RRF", "jsonb": "JSONB", "ann": "ANN"}


def concept_label(teaching_concept: str) -> str:
    """Render a `teaching_concept` slug as a human-readable label.

    Underscores become spaces and the first word is capitalized, so
    `semantic_intent_and_filters` becomes `Semantic intent and filters`. Tokens
    in `_CONCEPT_ACRONYMS` keep their conventional casing instead.

    Deliberately not a hand-written label per concept, which would drift from
    the query set; the slug remains the single source and only its acronyms are
    special-cased.
    """
    words = [_CONCEPT_ACRONYMS.get(word, word) for word in teaching_concept.split("_")]
    first, rest = words[0], words[1:]
    if first not in _CONCEPT_ACRONYMS.values():
        first = first.capitalize()
    return " ".join([first, *rest])


def label_per_query_metrics(
    per_query: list[dict[str, Any]],
    queries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach resolved query text and a human concept label to each row.

    `queries` must be resolved records (as `load_evaluation_queries`
    produces) covering every `query_id` present in `per_query`; every row
    in the canonical scorecard's `per_query_metrics` gets exactly the two
    new keys `query_text` and `concept_label` alongside its existing
    `query_id`, `recall@k`, `reciprocal_rank`, and `ndcg@k` fields.
    """
    by_query_id = {query["query_id"]: query for query in queries}
    labeled: list[dict[str, Any]] = []
    for row in per_query:
        query = by_query_id[row["query_id"]]
        labeled.append(
            {
                **row,
                "query_text": query["query"],
                "concept_label": concept_label(query["teaching_concept"]),
            }
        )
    return labeled


def scored_query_set_sha256(queries: list[dict[str, Any]]) -> str:
    """Hash the resolved records that actually contribute to retrieval metrics."""
    payload = "\n".join(
        json.dumps(query, sort_keys=True, separators=(",", ":")) for query in queries
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ranked_result_sha256(ranked: dict[str, list[tuple[int, int]]]) -> str:
    """Hash exact per-query ordering without volatile run or latency fields."""
    normalized = {
        query_id: [[rank, product_id] for rank, product_id in sorted(results)]
        for query_id, results in sorted(ranked.items())
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_hard_negatives(
    queries: list[dict[str, Any]],
    ranked: dict[str, list[tuple[int, int]]],
) -> None:
    """Prove the graded hard negatives stay out of the returned window.

    `hard_negative_ids` names, per query, the near-identical product that must not
    come back: a refurbished sibling, a non-carbon shoe, the same subcategory under a
    different model identity. `docs/lab-golden-queries.md` calls these
    validator-owned controls, and G-012's declared behavior is that they are "removed
    inside every retrieval arm".

    Nothing enforced that. `tests/test_canonical_evals.py` asserts the *judgments*
    grade every hard negative 0, which is a property of the fixture, and
    `validate_lab.py` checks eligibility against the mission filters, which is a
    different claim: a hard negative can satisfy every filter and still be the wrong
    product. So a documented control could regress silently while every gate stayed
    green.

    Deliberately not appended to `deterministic_release_checks`. That field is
    compared field-for-field by `verify_scorecard`, so recording these would force a
    new baseline for a check that adds no new measurement — it only refuses a
    retrieval result the fixtures already said was wrong.
    """
    for query in queries:
        negatives = query.get("hard_negative_ids") or []
        if not negatives:
            continue
        ranked_ids = [
            product_id for _, product_id in sorted(ranked.get(query["query_id"], []))
        ]
        retrieved = [product_id for product_id in negatives if product_id in ranked_ids]
        if retrieved:
            raise ValueError(
                f"{query['query_id']} returned hard negative(s) {retrieved} at "
                f"rank(s) {[ranked_ids.index(p) + 1 for p in retrieved]}; these "
                "products are graded 0 and must not reach the result window. Fix the "
                "eligibility gate or the retrieval representation."
            )


def validate_release_checks(
    queries: list[dict[str, Any]],
    ranked: dict[str, list[tuple[int, int]]],
) -> list[dict[str, Any]]:
    """Prove fixture-specific behavior that aggregate metrics can obscure."""
    passed: list[dict[str, Any]] = []
    for query in queries:
        ranked_ids = [
            product_id for _, product_id in sorted(ranked.get(query["query_id"], []))
        ]
        for check in query.get("release_checks", []):
            check_type = check.get("type")
            product_id = check.get("product_id")
            if not isinstance(product_id, int):
                raise TypeError(
                    f"{query['query_id']} release check has product_id={product_id!r}; "
                    "use an integer catalog product ID."
                )
            if check_type == "top_rank":
                if not ranked_ids or ranked_ids[0] != product_id:
                    raise ValueError(
                        f"{query['query_id']} requires product {product_id} at final "
                        f"rank 1; found top results {ranked_ids[:5]}. Fix the "
                        "retrieval representation or explicit ranking policy."
                    )
            elif check_type == "present_top_k":
                check_k = check.get("k")
                if not isinstance(check_k, int) or check_k < 1:
                    raise ValueError(
                        f"{query['query_id']} release check has k={check_k!r}; "
                        "use a positive integer."
                    )
                if product_id not in ranked_ids[:check_k]:
                    raise ValueError(
                        f"{query['query_id']} requires product {product_id} in the "
                        f"top {check_k}; found {ranked_ids[:check_k]}. Fix the "
                        "retrieval representation or candidate-generation path."
                    )
            else:
                raise ValueError(
                    f"{query['query_id']} release check type={check_type!r}; "
                    "use 'top_rank' or 'present_top_k'."
                )
            entry = {
                "query_id": query["query_id"],
                "type": check_type,
                "product_id": product_id,
                **({"k": check["k"]} if check_type == "present_top_k" else {}),
            }
            if "query" in query:
                entry["query_text"] = query["query"]
            if "teaching_concept" in query:
                entry["concept_label"] = concept_label(query["teaching_concept"])
            passed.append(entry)
    return passed


def scorecard_checkpoint_path(results_path: Path) -> Path:
    """Return the sidecar used to resume a partially completed measurement."""
    return results_path.with_suffix(f"{results_path.suffix}.checkpoint.json")


def _checkpoint_identity(
    *,
    queries_path: Path,
    queries: list[dict[str, Any]],
    k: int,
    settings: Any,
    profile: Any,
    database_environment: dict[str, Any],
    strategy: str,
) -> dict[str, Any]:
    return {
        "query_set_sha256": query_set_sha256(queries_path),
        "scored_query_set_sha256": scored_query_set_sha256(queries),
        "retrieval_fingerprint": compute_retrieval_fingerprint(),
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
        "retrieval_profile": profile.model_dump(mode="json"),
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "database_version": database_environment["database_version"],
            "vector_extension_version": database_environment[
                "vector_extension_version"
            ],
            "instance_class": settings.aurora_instance_class,
        },
        "database_instance_id": database_environment["database_instance_id"],
        "strategy": strategy,
    }


def _load_checkpoint(
    path: Path,
    expected_identity: dict[str, Any],
) -> tuple[set[str], dict[str, list[tuple[int, int]]], dict[str, list[dict[str, Any]]]]:
    if not path.exists():
        return set(), {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Scorecard checkpoint {path} is unreadable: {error}. "
            "Rerun with --restart to discard it."
        ) from error
    if payload.get("identity") != expected_identity:
        raise ValueError(
            "Scorecard checkpoint provenance drifted from the current query, "
            f"source, model, retrieval, or Aurora contract: {path}. Rerun with "
            "--restart to discard it rather than mixing measurements."
        )
    completed = payload.get("completed_query_ids")
    ranked_payload = payload.get("ranked")
    rows = payload.get("rows")
    if (
        not isinstance(completed, list)
        or not isinstance(ranked_payload, dict)
        or not isinstance(rows, dict)
        or any(
            not isinstance(query_id, str)
            or query_id not in ranked_payload
            or query_id not in rows
            for query_id in completed
        )
    ):
        raise ValueError(
            f"Scorecard checkpoint {path} has an invalid completion shape. "
            "Rerun with --restart to discard it."
        )
    ranked = {
        query_id: [(int(rank), int(product_id)) for rank, product_id in results]
        for query_id, results in ranked_payload.items()
        if query_id in completed
    }
    checkpoint_rows = {
        query_id: list(query_rows)
        for query_id, query_rows in rows.items()
        if query_id in completed
    }
    return set(completed), ranked, checkpoint_rows


def _write_checkpoint(
    path: Path,
    *,
    identity: dict[str, Any],
    completed: set[str],
    ranked: dict[str, list[tuple[int, int]]],
    rows: dict[str, list[dict[str, Any]]],
) -> None:
    payload = {
        "version": 1,
        "identity": identity,
        "completed_query_ids": sorted(completed),
        "ranked": {
            query_id: [[rank, product_id] for rank, product_id in results]
            for query_id, results in ranked.items()
            if query_id in completed
        },
        "rows": {
            query_id: query_rows
            for query_id, query_rows in rows.items()
            if query_id in completed
        },
    }
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def search_with_db_retry(
    retrieval: Any,
    request: SearchRequest,
    *,
    query_id: str,
    retry_delays: Sequence[float] = SCORECARD_DB_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry one scorecard sample only for transient psycopg connection failures."""
    for attempt in range(len(retry_delays) + 1):
        try:
            return retrieval.search(request)
        except (psycopg.InterfaceError, psycopg.OperationalError) as error:
            if attempt == len(retry_delays):
                raise
            delay = retry_delays[attempt]
            print(
                f"{query_id} Aurora connection failed on attempt {attempt + 1}/"
                f"{len(retry_delays) + 1}: {type(error).__name__}. "
                f"Retrying this query in {delay:g}s.",
                file=sys.stderr,
            )
            sleep(delay)
    raise AssertionError("scorecard retry loop exited without a result")


def run_scored_queries(
    queries: list[dict[str, Any]],
    retrieval: Any,
    *,
    k: int,
    checkpoint_path: Path,
    checkpoint_identity: dict[str, Any],
    retry_delays: Sequence[float] = SCORECARD_DB_RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[dict[str, Any]]]]:
    """Run or resume production retrieval one query at a time."""
    completed, ranked, rows = _load_checkpoint(
        checkpoint_path,
        checkpoint_identity,
    )
    query_ids = {query["query_id"] for query in queries}
    unexpected = completed - query_ids
    if unexpected:
        raise ValueError(
            f"Scorecard checkpoint contains unknown queries {sorted(unexpected)}. "
            "Rerun with --restart to discard it."
        )

    for index, query in enumerate(queries, 1):
        query_id = query["query_id"]
        if query_id in completed:
            print(f"{index}/{len(queries)} {query_id} (resumed)")
            continue
        response = search_with_db_retry(
            retrieval,
            SearchRequest(
                query=query["query"],
                filters=SearchFilters.model_validate(query.get("filters") or {}),
                limit=k,
                include_diagnostics=True,
                rerank=True,
                session_id="canonical-release-eval",
            ),
            query_id=query_id,
            retry_delays=retry_delays,
            sleep=sleep,
        )
        ranked[query_id] = [
            (result.signals.final_rank, result.product_id)
            for result in response.results
            if result.signals is not None
        ]
        rows[query_id] = [
            {
                "query_id": query_id,
                "product_id": product_id,
                "rank": rank,
                "search_event_id": str(response.search_event_id),
                "strategy": (
                    response.diagnostics.strategy
                    if response.diagnostics
                    else "unavailable"
                ),
                "total_latency_ms": (
                    response.diagnostics.total_latency_ms
                    if response.diagnostics
                    else None
                ),
            }
            for rank, product_id in ranked[query_id]
        ]
        completed.add(query_id)
        _write_checkpoint(
            checkpoint_path,
            identity=checkpoint_identity,
            completed=completed,
            ranked=ranked,
            rows=rows,
        )
        print(f"{index}/{len(queries)} {query_id}")
    return ranked, rows


def _write_results(
    path: Path,
    queries: list[dict[str, Any]],
    rows: dict[str, list[dict[str, Any]]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()
        for query in queries:
            writer.writerows(rows[query["query_id"]])
    _write_ranked_results(RANKED_RESULTS_PATH, queries, rows)


def _write_ranked_results(
    path: Path,
    queries: list[dict[str, Any]],
    rows: dict[str, list[dict[str, Any]]],
) -> None:
    """The committed ranking, reduced to what reproduces the metrics.

    `benchmarks/results/` is git-ignored because per-run artifacts carry live
    identifiers -- `search_event_id` addresses a row in `mosaic.search_event`, and
    latency describes one host. That left the ablation unable to run from a clean
    clone at all, since it rebuilds its served arm from that CSV.

    This carries only `query_id,product_id,rank`: enough to recompute Recall, MRR,
    nDCG and the ranked-result hash, and nothing that identifies a run, a host, or
    a cluster. It is committed deliberately, so a clean clone can reproduce the
    published numbers without a database.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(RANKED_RESULT_FIELDNAMES)
        for query in queries:
            for row in rows[query["query_id"]]:
                writer.writerow([row["query_id"], row["product_id"], row["rank"]])


def _scorecard_only_revision_delta(
    baseline_revision: str,
    measured_revision: str,
) -> bool:
    """Allow the commit that records a baseline without allowing code drift."""
    if baseline_revision == measured_revision:
        return True
    try:
        is_ancestor = (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO),
                    "merge-base",
                    "--is-ancestor",
                    baseline_revision,
                    measured_revision,
                ],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )
        changed_paths = set(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO),
                    "diff",
                    "--name-only",
                    f"{baseline_revision}..{measured_revision}",
                    "--",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return is_ancestor and changed_paths <= POST_MEASUREMENT_ARTIFACT_PATHS


def _validate_measurement_source(settings: Any) -> None:
    """Fail before Aurora or model work when source provenance is not immutable."""
    if settings.source_worktree_dirty:
        raise ValueError(
            "Canonical scorecard measurement requires a clean committed source; "
            "commit or remove the current worktree changes before running the "
            "Aurora-backed scorecard."
        )
    if not FULL_GIT_SHA.fullmatch(settings.source_revision):
        raise ValueError(
            "Canonical scorecard measurement requires a full 40-character Git SHA; "
            f"found source revision {settings.source_revision!r}. Set "
            "MOSAIC_SOURCE_REVISION to the immutable commit or run from a Git "
            "checkout."
        )
    if not settings.aurora_instance_class:
        raise ValueError(
            "Canonical scorecard provenance requires AURORA_INSTANCE_CLASS; found "
            "it unset. Export the live Aurora writer class, for example "
            "AURORA_INSTANCE_CLASS=db.r8g.2xlarge, before running the billed "
            "scorecard."
        )


def measured_scorecard(
    queries_path: Path,
    results_path: Path,
    *,
    k: int,
) -> dict[str, Any]:
    """Run the production retrieval and reranking service for every query."""
    canonical_queries = load_evaluation_queries(queries_path)
    queries, excluded_agent_contract_queries = product_retrieval_queries(
        canonical_queries
    )
    settings = get_settings()
    _validate_measurement_source(settings)
    with connect() as connection:
        validate_query_contract(connection, queries)
        database_environment = dict(
            connection.execute(
                """
                SELECT aurora_db_instance_identifier() AS database_instance_id,
                       current_setting('server_version') AS database_version,
                       (
                           SELECT extversion
                           FROM pg_extension
                           WHERE extname = 'vector'
                       ) AS vector_extension_version
                """
            ).fetchone()
        )

    retrieval = get_retrieval_service()
    profile = retrieval._profile(SearchRequest(query="scorecard provenance", limit=k))
    strategy = retrieval._strategy()
    checkpoint_identity = _checkpoint_identity(
        queries_path=queries_path,
        queries=queries,
        k=k,
        settings=settings,
        profile=profile,
        database_environment=database_environment,
        strategy=strategy,
    )
    ranked, rows = run_scored_queries(
        queries,
        retrieval,
        k=k,
        checkpoint_path=scorecard_checkpoint_path(results_path),
        checkpoint_identity=checkpoint_identity,
    )
    _write_results(results_path, queries, rows)

    all_judgments = load_judgments(queries_path)
    validate_hard_negatives(queries, ranked)
    release_checks = validate_release_checks(queries, ranked)
    metrics = evaluate(
        {query["query_id"]: all_judgments[query["query_id"]] for query in queries},
        ranked,
        k,
    )
    per_query_metrics = label_per_query_metrics(metrics["per_query"], canonical_queries)
    return {
        "query_set": str(queries_path),
        "query_set_sha256": query_set_sha256(queries_path),
        "scored_query_set_sha256": scored_query_set_sha256(queries),
        "retrieval_fingerprint": compute_retrieval_fingerprint(),
        # How this was measured and served, held apart from what retrieval does.
        # Deliberately not folded into retrieval_fingerprint: that hash gates a
        # paid measurement, so coupling it to the harness would let a
        # console-output tweak invalidate a billed run.
        "scorecard_methodology_sha256": compute_scorecard_methodology_sha256(),
        "canonical_query_count": len(canonical_queries),
        "product_retrieval_query_count": metrics["query_count"],
        "excluded_agent_contract_queries": excluded_agent_contract_queries,
        "deterministic_release_checks": release_checks,
        "ranked_result_sha256": ranked_result_sha256(ranked),
        "per_query_metrics": per_query_metrics,
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
        "retrieval_profile": profile.model_dump(),
        # The settings above, hashed, so serve time can compare them. Recorded
        # separately because no file hash can see them: environment variables
        # beat db/config/retrieval.yaml inside
        # `scripts.retrieval_profile._resolve`, so RRF_K=1 changes every result
        # here with `retrieval_fingerprint` sitting perfectly still.
        #
        # Computed from the resolved profile rather than from `profile` above:
        # `RetrievalService._profile` overwrites `result_limit` and
        # `authorized_limit` from the request, which are facts about this one
        # measurement call rather than about the configuration. Hashing them
        # would compare a request against a configuration at serve time and
        # could never match. They stay pinned regardless -- `retrieval_profile`
        # is compared field-for-field by `verify_scorecard` below.
        "retrieval_settings_sha256": compute_live_retrieval_settings_sha256(),
        "hnsw_settings": {
            "ef_search": profile.ef_search,
            "iterative_scan": profile.iterative_scan,
            "max_scan_tuples": profile.max_scan_tuples,
            "scan_mem_multiplier": profile.scan_mem_multiplier,
        },
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "database_version": database_environment["database_version"],
            "vector_extension_version": database_environment[
                "vector_extension_version"
            ],
            "instance_class": settings.aurora_instance_class,
        },
        "database_instance_id": database_environment["database_instance_id"],
        "measured_at": datetime.now(UTC).isoformat(),
        "strategy": strategy,
        "metrics": {
            f"recall@{k}": metrics[f"recall@{k}"],
            "mrr": metrics["mrr"],
            f"ndcg@{k}": metrics[f"ndcg@{k}"],
        },
    }


def verify_scorecard(measured: dict[str, Any], baseline: dict[str, Any]) -> None:
    """Fail release validation when measured quality or provenance changes."""
    for field in (
        "query_set_sha256",
        "scored_query_set_sha256",
        "retrieval_fingerprint",
        "canonical_query_count",
        "product_retrieval_query_count",
        "excluded_agent_contract_queries",
        "deterministic_release_checks",
        "ranked_result_sha256",
        "k",
        "models",
        "dataset_manifest_sha256",
        "retrieval_profile",
        "retrieval_settings_sha256",
        "hnsw_settings",
        "aurora_configuration",
        "database_instance_id",
        "strategy",
    ):
        if measured[field] != baseline.get(field):
            raise ValueError(
                f"Canonical scorecard {field} drifted: measured={measured[field]!r}; "
                f"baseline={baseline.get(field)!r}. Establish a new measured baseline "
                "only after reviewing the retrieval change."
            )
    source = measured.get("source") or {}
    if not source.get("revision") or not isinstance(source.get("worktree_dirty"), bool):
        raise ValueError(
            "Canonical scorecard source provenance is incomplete: "
            f"measured={source!r}. Record revision and worktree_dirty."
        )
    if source["worktree_dirty"]:
        raise ValueError(
            "Canonical scorecard source is dirty: "
            f"measured={source!r}; commit the reviewed source and rerun the "
            "production scorecard before release."
        )
    baseline_source = baseline.get("source") or {}
    if not baseline_source.get("revision"):
        raise ValueError(
            "Canonical scorecard baseline source revision is missing: "
            f"baseline={baseline_source!r}; regenerate it from the clean release "
            "revision."
        )
    if baseline_source.get("worktree_dirty") is not False:
        raise ValueError(
            "Canonical scorecard baseline was not captured from a clean source: "
            f"baseline={baseline_source!r}; establish it from a committed checkout."
        )
    if not _scorecard_only_revision_delta(
        baseline_source["revision"],
        source["revision"],
    ):
        raise ValueError(
            "Canonical scorecard source revision drifted: "
            f"measured={source['revision']!r}; "
            f"baseline={baseline_source['revision']!r}. Commit the reviewed "
            "release, inspect its Aurora ranks, and write a new baseline. The "
            "only permitted later commits are the generated scorecard, ranked "
            "results, and stage-ablation artifacts."
        )
    for metric, expected in baseline["metrics"].items():
        actual = measured["metrics"].get(metric)
        if actual is None or actual < expected:
            raise ValueError(
                f"Canonical scorecard regressed for {metric}: measured={actual}; "
                f"baseline={expected}. Inspect per-query ranks before release."
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("data/evals/canonical_queries.jsonl"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("benchmarks/results/canonical_served_results.csv"),
    )
    parser.add_argument(
        "--scorecard",
        type=Path,
        default=Path("data/evals/canonical_scorecard.json"),
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the current measured scorecard after an explicit review.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard a partial checkpoint and rerun every scorecard query.",
    )
    args = parser.parse_args()
    args.results.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = scorecard_checkpoint_path(args.results)
    if args.restart:
        checkpoint_path.unlink(missing_ok=True)
    measured = measured_scorecard(args.queries, args.results, k=args.k)
    if args.write_baseline:
        if measured["source"]["worktree_dirty"]:
            raise SystemExit(
                "Refusing to write a canonical baseline from a dirty source; "
                "commit the reviewed changes, rerun, inspect the ranks, then use "
                "--write-baseline."
            )
        args.scorecard.write_text(
            json.dumps(measured, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote measured baseline {args.scorecard}")
        checkpoint_path.unlink(missing_ok=True)
        return
    if not args.scorecard.exists():
        raise SystemExit(
            f"Canonical scorecard is missing: {args.scorecard}. Run with "
            "--write-baseline only after reviewing measured ranks."
        )
    verify_scorecard(
        measured,
        json.loads(args.scorecard.read_text(encoding="utf-8")),
    )
    checkpoint_path.unlink(missing_ok=True)
    print(json.dumps(measured, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
