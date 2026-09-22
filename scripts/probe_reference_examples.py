#!/usr/bin/env python3
"""Locate reviewed ESCI matches in real search responses; never grade unreviewed rows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_reference_examples import validate_bundle
from scripts.validate_lab import _request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    bundle = json.loads(
        (ROOT / "data/evals/references/reviewed_sources.json").read_text()
    )
    validate_bundle(bundle)
    missions = json.loads((ROOT / "data/evals/mosaic_labs_missions.json").read_text())
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "scope": "Three reviewed ESCI queries against the production Amazon catalog. WANDS records are a separate source comparison, not part of this search corpus. Unreviewed results are ungraded; no whole-catalog quality metric is calculated.",
        "runs": [],
    }
    for case in bundle["cases"]:
        if case["dataset"] != "esci":
            continue
        payload = {
            "query": case["query"],
            "filters": {},
            "limit": missions["missions"][0]["top_k"],
            "include_diagnostics": True,
            "rerank": True,
        }
        response = _request(args.base_url, "/api/search", payload)
        pool = _request(
            args.base_url, f"/api/retrieval/events/{response['search_event_id']}"
        )
        products = response["results"]
        reviewed_ids = {p["catalog_product_id"] for p in case["products"]}
        matches = []
        for reference in case["products"]:
            pid = reference["catalog_product_id"]
            match = next((p for p in products if p["product_id"] == pid), None)
            matches.append(
                {
                    "product_id": pid,
                    "asin": reference["source_product_id"],
                    "source_label": reference["label"],
                    "in_saved_pool": any(
                        p["product_id"] == pid for p in pool["candidates"]
                    ),
                    "displayed_rank": next(
                        (
                            i
                            for i, p in enumerate(products, 1)
                            if p["product_id"] == pid
                        ),
                        None,
                    ),
                    "current_source_matches_review": None
                    if match is None
                    else match["sku"] == reference["source_product_id"]
                    and any(
                        s.get("revision") == reference["catalog_source_sha256"]
                        for s in match["sources"]
                    ),
                }
            )
        report["runs"].append(
            {
                "case": case["id"],
                "category": case["category"],
                "request": payload,
                "search_event_id": response["search_event_id"],
                "reviewed_matches": matches,
                "ungraded_displayed_results": sum(
                    p["product_id"] not in reviewed_ids for p in products
                ),
                "displayed_products": [
                    {
                        "product_id": p["product_id"],
                        "asin": p["sku"],
                        "title": p["title"],
                    }
                    for p in products
                ],
            }
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"case": case["id"], "reviewed_matches": matches}), flush=True)


if __name__ == "__main__":
    main()
