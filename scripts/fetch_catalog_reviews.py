#!/usr/bin/env python3
"""Select bounded, traceable review samples without storing the category corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog_metadata import REVISION, validate_range
from scripts.prepare_real_catalog import canonical, sha256

REVIEW_SOURCES = {
    "Electronics": (
        22616233652,
        "bf11cf9c94c23ead7d3ffb174d18231fad8fcd76e72ad167f538a5599a38de8e",
    ),
    "Office_Products": (
        5776792834,
        "82cc49670098220a314d398ceff6434599b54c27af5fa00ab9c0b4af9d9d9011",
    ),
}
RANGE_BYTES = 16 * 1024 * 1024


def source_identity(category: str) -> dict:
    """Identify immutable source bytes independently of the selected sample."""
    size, digest = REVIEW_SOURCES[category]
    return {
        "revision": REVISION,
        "url": "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
        f"resolve/{REVISION}/raw/review_categories/{category}.jsonl",
        "bytes": size,
        "sha256": digest,
    }


def review_record(raw_line: bytes, offset: int) -> dict:
    """Preserve review and variant identity with reproducible source locations."""
    original = json.loads(raw_line)
    valid = (
        isinstance(original, dict)
        and all(
            isinstance(original.get(k), str) and original[k].strip()
            for k in ("parent_asin", "asin", "text")
        )
        and isinstance(original.get("title"), str)
        and type(original.get("rating")) in (int, float)
        and math.isfinite(original["rating"])
        and 1 <= original["rating"] <= 5
        and type(original.get("timestamp")) is int
        and 0 < original["timestamp"] < 32503680000000
        and type(original.get("helpful_vote")) is int
        and original["helpful_vote"] >= 0
        and type(original.get("verified_purchase")) is bool
    )
    if not valid:
        raise ValueError(
            f"Review shape rule: invalid source record at byte {offset}; inspect its original fields, do not fill missing evidence."
        )
    return {
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "raw_line": raw_line.decode("utf-8"),
        "source_location": {
            "offset": offset,
            "length": len(raw_line),
            "line_sha256": hashlib.sha256(raw_line).hexdigest(),
        },
    }


def verify_review(row: dict) -> None:
    """Reject altered text, provenance or product identity before ingestion."""
    raw = row["raw_line"].encode("utf-8")
    rebuilt = review_record(raw, row["source_location"]["offset"])
    if rebuilt != row:
        raise ValueError(
            f"Review integrity rule: record at byte {row['source_location']['offset']} changed; restore the pinned source line."
        )


def rating_group(rating: float) -> str:
    return "critical" if rating <= 2 else "positive" if rating >= 4 else "mixed"


def select_reviews(rows: list[dict], per_group: int) -> list[dict]:
    """Keep positive and critical experiences separate, without claiming balance."""
    grouped: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        review = row["original"]
        key = (review["parent_asin"], rating_group(review["rating"]))
        grouped.setdefault(key, {})[row["source_record_sha256"]] = row
    selected = []
    for key in sorted(grouped):
        selected.extend(
            sorted(
                grouped[key].values(),
                key=lambda row: (
                    -row["original"]["helpful_vote"],
                    -row["original"]["timestamp"],
                    row["source_record_sha256"],
                ),
            )[:per_group]
        )
    return selected


def consume_range(
    data: bytes, start: int, *, final: bool, parents: set[str]
) -> tuple[list[dict], int, int]:
    """Consume complete JSONL rows; the next range re-reads an unfinished tail."""
    used = len(data) if final else data.rfind(b"\n") + 1
    if not used:
        raise ValueError(
            f"Review boundary rule: no complete row at byte {start}; fetch a larger source range."
        )
    found, count, position = [], 0, start
    for line in data[:used].splitlines(keepends=True):
        raw = json.loads(line)
        count += 1
        if (
            raw.get("parent_asin") in parents
            and isinstance(raw.get("text"), str)
            and raw["text"].strip()
        ):
            found.append(review_record(line, position))
        position += len(line)
    return found, used, count


def fetch_range(source: dict, start: int, end: int) -> bytes:
    for attempt in range(5):
        try:
            request = urllib.request.Request(
                source["url"] + f"?download=true&range_start={start}&range_end={end}",
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "Mosaic-review-evidence/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                validate_range(
                    response.status,
                    response.headers.get("Content-Range"),
                    start,
                    end,
                    source["bytes"],
                )
                data = response.read(end - start + 2)
            if len(data) != end - start + 1:
                raise ValueError(
                    f"Review byte-count rule: range {start}-{end} is incomplete; retry it before advancing."
                )
            return data
        except (OSError, urllib.error.URLError):
            if attempt == 4:
                raise
            time.sleep(min(2**attempt, 16))
    raise AssertionError("unreachable")


def fetch(
    category: str, destination: Path, parents: set[str], scan_bytes: int, per_group: int
) -> dict:
    """Resume a prefix scan, keeping only bounded examples and range receipts."""
    if not parents or scan_bytes < RANGE_BYTES or per_group < 1:
        raise ValueError(
            "Review selection rule: require parent IDs, at least one range, and a positive sample size; fix the scan arguments."
        )
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{category}-reviews.json"
    source = source_identity(category)
    identity = {
        "source": source,
        "parent_asins": sorted(parents),
        "reviews_per_rating_group": per_group,
    }
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {
            **identity,
            "next_byte": 0,
            "records_scanned": 0,
            "reviews": [],
            "ranges": [],
            "selection_policy": "Highest helpful-vote count, then newest, within positive (4–5), mixed (3), and critical (1–2) groups of the scanned prefix. This is not a representative customer sample.",
            "full_source_hash_verified": False,
        }
    )
    if any(state.get(key) != value for key, value in identity.items()):
        raise ValueError(
            "Review resume rule: source or selection differs from the checkpoint; use a new destination."
        )
    for row in state["reviews"]:
        verify_review(row)
    stop = min(source["bytes"], state["next_byte"] + scan_bytes)
    while state["next_byte"] < stop:
        start = state["next_byte"]
        end = min(stop, start + RANGE_BYTES) - 1
        data = fetch_range(source, start, end)
        if b"\n" not in data and end + 1 == stop and stop < source["bytes"]:
            break
        found, used, count = consume_range(
            data, start, final=end + 1 == source["bytes"], parents=parents
        )
        state["reviews"] = select_reviews([*state["reviews"], *found], per_group)
        state["next_byte"] = start + used
        state["records_scanned"] += count
        state["ranges"].append(
            {"start": start, "end": end, "sha256": hashlib.sha256(data).hexdigest()}
        )
        state["complete_source_scan"] = state["next_byte"] == source["bytes"]
        state["coverage"] = {
            parent: sum(
                row["original"]["parent_asin"] == parent for row in state["reviews"]
            )
            for parent in sorted(parents)
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
        print(
            json.dumps(
                {
                    "category": category,
                    "bytes_scanned": state["next_byte"],
                    "records_scanned": state["records_scanned"],
                    "reviews": len(state["reviews"]),
                    "coverage": state["coverage"],
                }
            ),
            flush=True,
        )
        if end + 1 == stop:
            break
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=REVIEW_SOURCES)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--examples", type=Path, default=ROOT / "data/real-catalog-examples.json"
    )
    parser.add_argument("--scan-mib", type=int, default=256)
    parser.add_argument("--reviews-per-rating-group", type=int, default=3)
    args = parser.parse_args()
    examples = json.loads(args.examples.read_text())["examples"]
    parents = {
        row["product_id"]
        for row in examples
        if row.get("selected_in_bulk") and row.get("source_department") == args.category
    }
    fetch(
        args.category,
        args.destination,
        parents,
        args.scan_mib * 1024 * 1024,
        args.reviews_per_rating_group,
    )


if __name__ == "__main__":
    main()
