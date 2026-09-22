#!/usr/bin/env python3
"""Measure required lab tradeoffs without changing products or saved settings."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.validate_lab import LabValidationError, _request, _require
from service import lab_checks


def paired_searches(before: dict, after: dict, mission: dict) -> dict:
    """Reject an apparent repair produced by changing the question or dataset."""
    old, new = before["run"], after["run"]
    for key in (
        "query_text",
        "filters",
        "dataset_manifest_sha256",
        "retrieval_profile",
        "embedding_model_id",
        "rerank_model_id",
        "retrieval_strategy",
    ):
        _require(
            old.get(key) is not None and old[key] == new.get(key),
            f"Paired-search rule: {key} differs or is absent; repeat the identical request on the same dataset and settings.",
        )
    _require(
        new["query_text"] == mission["query"] and new["filters"] == mission["filters"],
        "Mission request rule: saved request differs; use the declared lab request.",
    )
    target = mission["target_product_ids"][0]
    old_ids = {row["product_id"] for row in before["candidates"]}
    row = next(
        (row for row in after["candidates"] if row["product_id"] == target), None
    )
    _require(
        bool(old_ids) and target not in old_ids and row is not None,
        f"Pool recovery rule: target {target} must be absent before and present after; save the actual broken and repaired runs.",
    )
    _require(
        all(row.get("eligible") is True for row in after["candidates"]),
        "Eligibility rule: repaired pool has an ineligible or unchecked row; inspect production filters.",
    )
    return {
        "target": target,
        "before_in_pool": False,
        "after_in_pool": True,
        "combined_position": row["fused_rank"],
        "final_position": row["result_rank"],
        "before_event": old["search_event_id"],
        "after_event": new["search_event_id"],
    }


def citation_challenges(agent: dict, resolved: dict[int, dict]) -> dict:
    """Challenge the shared receipt checker and the production synthesis guard."""
    from service.models import EvidenceRecord, ProductSummary
    from service.synthesis import (
        SynthesisOutputError,
        _validate_product_claim_citations,
    )

    citations = agent.get("citations") or []
    _require(
        bool(citations)
        and all(
            lab_checks._citation_resolves(c, resolved.get(c["evidence_id"]))
            for c in citations
        ),
        "Citation positive control failed; fetch a current answer whose citations resolve before attempting negative tests.",
    )
    first = citations[0]
    other = next((c for c in citations if c["product_id"] != first["product_id"]), None)
    _require(
        other is not None,
        "Cross-product challenge needs two cited products; use the Lab 3 monitor and chair answer.",
    )
    mutations = {
        "another_product_record": {**first, "evidence_id": other["evidence_id"]},
        "changed_quote": {
            **first,
            "quote": first["quote"] + " [altered for this local test]",
        },
        "changed_revision": {**first, "revision": first["revision"] + "-changed"},
    }
    rejected = {
        name: not lab_checks._citation_resolves(c, resolved.get(c["evidence_id"]))
        for name, c in mutations.items()
    }
    _require(
        all(rejected.values()),
        f"Citation challenge rule: accepted a mutation {rejected}; inspect the shared citation checker.",
    )

    products = [
        ProductSummary.model_validate(p)
        for p in agent["recommendations"]
        if p["product_id"] in {first["product_id"], other["product_id"]}
    ]
    records = [
        EvidenceRecord.model_validate(resolved[c["evidence_id"]])
        for c in (first, other)
    ]
    product = next(p for p in products if p.product_id == first["product_id"])
    name = product.model or product.title
    _validate_product_claim_citations(
        f"{name} has a source record [1].", products, records
    )
    try:
        _validate_product_claim_citations(
            f"{name} has a source record [2].", products, records
        )
    except SynthesisOutputError as error:
        rejected["production_wrong_product_citation"] = str(error)
    else:
        raise LabValidationError(
            "Product-scope challenge accepted the other product's citation; inspect synthesis validation."
        )
    return {
        "positive_control": "accepted",
        "negative_controls": rejected,
        "scope": "Local checks against freshly resolved source records. No answer or database record was changed. These checks do not prove every possible claim is true.",
    }


def inspect_arms(receipt: dict, mission: dict) -> dict:
    """Call the installed generators with one shared vector and recorded settings."""
    import numpy as np

    from service.catalog_runtime import search_schema
    from service.db import connect
    from service.models import RetrievalProfile
    from service.retrieval import RetrievalService

    event = receipt["run"]
    profile = RetrievalProfile.model_validate(event["retrieval_profile"])
    service = RetrievalService()
    _require(
        service.settings.embedding_model_id == event["embedding_model_id"],
        "Embedding identity rule: current model differs from the saved search; use the original configuration.",
    )
    vector = np.asarray(
        service.embed_query(event["normalized_query"]), dtype=np.float32
    )
    schema = search_schema()
    filters = json.dumps(event["filters"])
    target = mission["target_product_ids"][0]
    statements = {
        "fts": (
            f"SELECT * FROM {schema}.search_fts(%s, %s::jsonb, %s)",
            (event["normalized_query"], filters, profile.fts_limit),
        ),
        "trigram": (
            f"SELECT * FROM {schema}.search_trigram(%s, %s::jsonb, %s, %s::real)",
            (
                event["normalized_query"],
                filters,
                profile.trigram_limit,
                profile.trigram_threshold,
            ),
        ),
        "semantic": (
            f"SELECT * FROM {schema}.search_vector(%s::vector, %s::jsonb, %s)",
            (vector, filters, profile.semantic_limit),
        ),
    }
    observations: dict[str, Any] = {}
    with connect() as conn:
        try:
            current = conn.execute(
                f"SELECT catalog_sha256 FROM {schema}.receipt WHERE singleton"
            ).fetchone()
            _require(
                current
                and current["catalog_sha256"] == event["dataset_manifest_sha256"],
                "Catalog identity rule: the search predates the current catalog; save a new search.",
            )
            service._configure_hnsw(conn, profile)
            for arm, (sql, args) in statements.items():
                started = time.perf_counter()
                rows = conn.execute(sql, args).fetchall()
                found = next((row for row in rows if row["product_id"] == target), None)
                observations[arm] = {
                    "rows": len(rows),
                    "target_rank": None if found is None else found[f"{arm}_rank"],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            control = lab_checks.load_case("semantic-eligibility")
            selective = json.dumps(control["filters"])
            eligible = conn.execute(
                f"SELECT count(*) AS n FROM {schema}.product_document d "
                f"WHERE embedding IS NOT NULL AND category_key = %s AND lower(brand_name) = lower(%s) "
                f"AND {schema}.matches_filters(d, %s::jsonb)",
                (
                    control["filters"]["category_key"],
                    control["filters"]["brand"],
                    selective,
                ),
            ).fetchone()["n"]
            _require(
                eligible > 0,
                "Filtered-scan control has no eligible rows; check the active catalog and filters before interpreting the scan.",
            )
            sql, _ = statements["semantic"]
            args = (vector, selective, profile.semantic_limit)
            scans = []
            for multiplier in dict.fromkeys((1.0, profile.scan_mem_multiplier)):
                trial = profile.model_copy(update={"scan_mem_multiplier": multiplier})
                service._configure_hnsw(conn, trial)
                started = time.perf_counter()
                rows = conn.execute(sql, args).fetchall()
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                plan = conn.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + sql, args
                ).fetchone()["QUERY PLAN"]
                scans.append(
                    {
                        "scan_mem_multiplier": multiplier,
                        "requested_rows": profile.semantic_limit,
                        "returned_rows": len(rows),
                        "elapsed_ms": elapsed,
                        "plan": plan,
                    }
                )
            observations["filtered_scan"] = {
                "query": event["normalized_query"],
                "filters": control["filters"],
                "eligible_products": eligible,
                "runs": scans,
                "interpretation": "One shared query vector. Row count is not recall; equal counts are a valid observation. Timings include client round trips and cache effects; this is not a benchmark.",
            }
        finally:
            conn.rollback()
    return {
        "search_event_id": event["search_event_id"],
        "target": target,
        "direct_searches": observations,
        "embedding_note": "A fresh query vector is shared by every probe. The original search vector is not stored; these are current generator measurements, not a byte-identical replay.",
    }


def inspect_ranking(before: dict, after: dict, mission: dict) -> dict:
    """Check paired pools and measure the installed function's head/tail preference."""
    from service.catalog_runtime import search_schema
    from service.db import connect

    result = paired_searches(before, after, mission)
    event = after["run"]
    configured = event["retrieval_profile"]["rrf_k"]
    positions = [
        row[key]
        for row in after["candidates"]
        for key in ("fts_rank", "trigram_rank", "semantic_rank")
        if row.get(key)
    ]
    _require(
        bool(positions) and max(positions) > 1,
        "Rank sensitivity rule: no tail rank to compare; inspect the saved full pool.",
    )
    measurements = []
    with connect() as conn:
        for value in sorted({max(1, configured // 2), configured, configured * 2}):
            row = conn.execute(
                f"SELECT {search_schema()}.reciprocal_rank_contribution(1, %s) AS head, "
                f"{search_schema()}.reciprocal_rank_contribution(%s, %s) AS tail",
                (value, max(positions), value),
            ).fetchone()
            _require(
                row["head"] > row["tail"] > 0,
                f"Rank decay rule: k={value}, first={row['head']}, tail={row['tail']}; restore source-rank contribution before tuning.",
            )
            measurements.append(
                {
                    "k": value,
                    "tail_rank": max(positions),
                    **row,
                    "head_to_tail_ratio": row["head"] / row["tail"],
                }
            )
        conn.rollback()
    return {
        **result,
        "rank_sensitivity": measurements,
        "stage_timings": event["diagnostics"],
        "interpretation": "This isolates the installed formula. It does not rerank another pool or establish which k is best. Use independently judged requests before changing production settings.",
    }


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("arms", "ranking", "citations"))
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    response = json.loads(args.response.read_text())
    if args.mode == "citations":
        resolved = {
            c["evidence_id"]: _request(
                args.api_url, f"/api/evidence/{c['evidence_id']}"
            )
            for c in response.get("citations", [])
        }
        report = citation_challenges(response, resolved)
    else:
        from service.catalog_runtime import active_dataset

        stage = "retrieve" if args.mode == "arms" else "rank"
        mission = lab_checks.load_mission(stage)
        _require(
            active_dataset() == mission["dataset_id"],
            f"Dataset selection rule: found {active_dataset()!r}; export MOSAIC_CATALOG_DATASET={mission['dataset_id']} before investigating.",
        )
        receipt = _request(
            args.api_url, f"/api/retrieval/events/{response['search_event_id']}"
        )
        _require(
            receipt["run"]["query_text"] == mission["query"]
            and receipt["run"]["filters"] == mission["filters"],
            "Mission request rule: this is a different request; save the declared lab search.",
        )
        if args.mode == "arms":
            report = inspect_arms(receipt, mission)
        else:
            if not args.before:
                parser.error("ranking needs --before from the broken search")
            before = json.loads(args.before.read_text())
            old = _request(
                args.api_url, f"/api/retrieval/events/{before['search_event_id']}"
            )
            report = inspect_ranking(old, receipt, mission)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
