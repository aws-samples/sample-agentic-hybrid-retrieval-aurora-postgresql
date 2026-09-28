#!/usr/bin/env python3
"""Scan one pinned review file in line-aligned parts, hash it whole, and write the release sample.

Each part is an ordinary `fetch_catalog_reviews.fetch` run seeded at a line
boundary with a byte budget that ends on the next boundary, so no row is split
or skipped. A separate ordered pass hashes the whole file against its pin. The
merge keeps the top reviews per rating group of the union of per-part tops,
which equals the whole-file top, and writes the compact release form directly
so the untrimmed union never has to be held or stored at once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog_reviews import (
    RANGE_BYTES,
    REVIEW_SOURCES,
    coverage_of,
    expand_review,
    fetch,
    fetch_range,
    select_reviews,
    source_identity,
    trim_sample,
)

POLICY = (
    "Highest helpful-vote count, then newest, within positive (4–5), mixed (3), and "
    "critical (1–2) groups of the scanned prefix. This is not a representative customer sample."
)


def boundaries(source: dict, parts: int) -> list[int]:
    """Split the file at the first line break after each even byte offset."""
    size = source["bytes"]
    bounds = [0]
    for index in range(1, parts):
        offset = size * index // parts
        window = fetch_range(source, offset, offset + 1_000_000 - 1)
        newline = window.find(b"\n")
        if newline < 0:
            raise ValueError(
                f"Part boundary rule: no line break within 1 MB after byte {offset}; use fewer parts."
            )
        bounds.append(offset + newline + 1)
    bounds.append(size)
    return bounds


def run_part(
    category: str,
    work: str,
    index: int,
    start: int,
    stop: int,
    parents: list[str],
    per_group: int,
) -> int:
    """Scan one part to its boundary; a rerun resumes from the part's checkpoint."""
    dest = Path(work) / f"p{index}"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{category}-reviews.json"
    if not path.exists():
        state = {
            "source": source_identity(category),
            "parent_asins": sorted(parents),
            "reviews_per_rating_group": per_group,
            "next_byte": start,
            "records_scanned": 0,
            "reviews": [],
            "ranges": [],
            "selection_policy": POLICY,
            "full_source_hash_verified": False,
        }
        path.write_text(json.dumps(state) + "\n")
    state = fetch(category, dest, set(parents), stop - start, per_group, workers=2)
    if state["next_byte"] != stop:
        raise ValueError(
            f"Part coverage rule: part {index} stopped at byte {state['next_byte']}, not {stop}; rerun the scan to resume it."
        )
    return index


def digest_pass(category: str, workers: int = 4) -> str:
    """Hash the whole file in byte order, independently of the part scans."""
    source = source_identity(category)
    size = source["bytes"]
    plan = [
        (start, min(size, start + RANGE_BYTES) - 1)
        for start in range(0, size, RANGE_BYTES)
    ]
    digest = hashlib.sha256()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        window: deque = deque()
        upcoming = iter(plan)
        for item in upcoming:
            window.append(pool.submit(fetch_range, source, *item))
            if len(window) >= workers * 2:
                break
        while window:
            future = window.popleft()
            for item in upcoming:
                window.append(pool.submit(fetch_range, source, *item))
                break
            digest.update(future.result())
    return digest.hexdigest()


def merge_release(
    category: str,
    work: Path,
    bounds: list[int],
    per_group: int,
    cap: int,
    observed: str,
) -> dict:
    """Merge complete parts into the compact release sample, trimmed to `cap` per rating group."""
    source = source_identity(category)
    kept, ranges, scanned, rejected, offsets, parents = [], [], 0, 0, [], []
    for index in range(len(bounds) - 1):
        state = json.loads(
            (work / f"p{index}" / f"{category}-reviews.json").read_text()
        )
        if state["next_byte"] != bounds[index + 1]:
            raise ValueError(
                f"Part coverage rule: part {index} ends at {state['next_byte']}, not {bounds[index + 1]}; finish the scan before merging."
            )
        kept += select_reviews([expand_review(row) for row in state["reviews"]], cap)
        ranges += state["ranges"]
        scanned += state["records_scanned"]
        rejected += state.get("records_rejected", 0)
        offsets += state.get("rejected_offsets") or []
        parents = state["parent_asins"]
    full = {
        "source": source,
        "parent_asins": parents,
        "reviews_per_rating_group": per_group,
        "next_byte": source["bytes"],
        "records_scanned": scanned,
        "records_rejected": rejected,
        "rejected_offsets": offsets[:20],
        "reviews": kept,
        "ranges": ranges,
        "selection_policy": POLICY,
        "complete_source_scan": True,
        "coverage": coverage_of(kept, parents),
        "source_sha256_observed": observed,
        "full_source_hash_verified": source["sha256"] is not None
        and observed == source["sha256"],
        "scan_parts": bounds,
    }
    if not full["full_source_hash_verified"]:
        raise ValueError(
            f"Source hash rule: {category} hashed {observed}, not the pinned {source['sha256']}; re-pin only after confirming the source revision."
        )
    return trim_sample(full, cap)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=REVIEW_SOURCES)
    parser.add_argument(
        "--parents",
        type=Path,
        required=True,
        help="JSON object mapping review category to parent ASINs",
    )
    parser.add_argument(
        "--work",
        type=Path,
        required=True,
        help="directory for resumable part checkpoints",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="directory for the release sample",
    )
    parser.add_argument("--parts", type=int, default=6)
    parser.add_argument("--reviews-per-rating-group", type=int, default=20)
    parser.add_argument("--release-per-rating-group", type=int, default=20)
    args = parser.parse_args()
    source = source_identity(args.category)
    parents = sorted(json.loads(args.parents.read_text())[args.category])
    bounds = boundaries(source, args.parts)
    started = time.monotonic()
    print(json.dumps({"bounds": bounds}), flush=True)
    with ProcessPoolExecutor(max_workers=args.parts + 1) as pool:
        digest_future = pool.submit(digest_pass, args.category)
        futures = [
            pool.submit(
                run_part,
                args.category,
                str(args.work),
                index,
                bounds[index],
                bounds[index + 1],
                parents,
                args.reviews_per_rating_group,
            )
            for index in range(args.parts)
        ]
        for future in futures:
            print(
                json.dumps(
                    {
                        "part_done": future.result(),
                        "elapsed": round(time.monotonic() - started),
                    }
                ),
                flush=True,
            )
        observed = digest_future.result()
    release = merge_release(
        args.category,
        args.work,
        bounds,
        args.reviews_per_rating_group,
        args.release_per_rating_group,
        observed,
    )
    args.destination.mkdir(parents=True, exist_ok=True)
    target = args.destination / f"{args.category}-reviews.json"
    target.write_text(json.dumps(release, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "reviews": len(release["reviews"]),
                "parents": len(release["coverage"]),
                "verified": release["full_source_hash_verified"],
                "bytes": target.stat().st_size,
                "elapsed": round(time.monotonic() - started),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
