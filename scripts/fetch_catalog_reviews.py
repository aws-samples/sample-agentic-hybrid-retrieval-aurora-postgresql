#!/usr/bin/env python3
"""Select bounded, traceable review samples without storing the category corpus.

The scan can cover a whole review file. Ranges are fetched by a small pool and
consumed in order, only lines that name a selected parent are decoded, and the
per-product sample is kept bounded while scanning so memory does not grow with
the file. Checkpoints are written every few GiB; a resumed scan re-reads at
most that much.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog_metadata import REVISION, validate_range
from scripts.prepare_real_catalog import canonical, sha256

# Home and Kitchen carries no pinned full-file hash yet: the file is 31 GB and
# the scanner records the hash of every range it reads instead. Pin it after
# the first complete scan reports its digest.
REVIEW_SOURCES = {
    "Electronics": (
        22616233652,
        "bf11cf9c94c23ead7d3ffb174d18231fad8fcd76e72ad167f538a5599a38de8e",
    ),
    "Office_Products": (
        5776792834,
        "82cc49670098220a314d398ceff6434599b54c27af5fa00ab9c0b4af9d9d9011",
    ),
    "Home_and_Kitchen": (31408889188, None),
}
RANGE_BYTES = 16 * 1024 * 1024
CHECKPOINT_RANGES = 256
PARENT_PATTERN = re.compile(rb'"parent_asin":\s*"([A-Z0-9]{10})"')


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


def expand_review(row: dict) -> dict:
    """Rebuild a full row from its source line; a compact release row carries no `original`."""
    raw = row["raw_line"].encode("utf-8")
    rebuilt = review_record(raw, row["source_location"]["offset"])
    if any(rebuilt[key] != value for key, value in row.items()):
        raise ValueError(
            f"Review integrity rule: record at byte {row['source_location']['offset']} changed; restore the pinned source line."
        )
    return rebuilt


def verify_review(row: dict) -> None:
    """Reject altered text, provenance or product identity before ingestion."""
    expand_review(row)


def compact_review(row: dict) -> dict:
    """Keep the bytes and their location; the decoded record is rebuilt on load."""
    return {key: value for key, value in row.items() if key != "original"}


def review_parent(row: dict) -> str:
    """Read the parent ASIN of a full or compact row without decoding the line."""
    if "original" in row:
        return row["original"]["parent_asin"]
    match = PARENT_PATTERN.search(row["raw_line"].encode("utf-8"))
    if match is None:
        raise ValueError(
            f"Review integrity rule: record at byte {row['source_location']['offset']} names no parent; restore the pinned source line."
        )
    return match.group(1).decode("ascii")


def rating_group(rating: float) -> str:
    return "critical" if rating <= 2 else "positive" if rating >= 4 else "mixed"


def _order(row: dict) -> tuple:
    return (
        -row["original"]["helpful_vote"],
        -row["original"]["timestamp"],
        row["source_record_sha256"],
    )


def select_reviews(rows: list[dict], per_group: int) -> list[dict]:
    """Keep positive and critical experiences separate, without claiming balance."""
    grouped: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        review = row["original"]
        key = (review["parent_asin"], rating_group(review["rating"]))
        grouped.setdefault(key, {})[row["source_record_sha256"]] = row
    selected = []
    for key in sorted(grouped):
        selected.extend(sorted(grouped[key].values(), key=_order)[:per_group])
    return selected


class BoundedSample:
    """Per (parent, rating group) buffers trimmed while scanning, so memory stays bounded."""

    def __init__(self, per_group: int, rows: list[dict] | None = None):
        self.per_group = per_group
        self.groups: dict[tuple[str, str], dict[str, dict]] = {}
        for row in rows or []:
            self.add(row)

    def add(self, row: dict) -> None:
        review = row["original"]
        key = (review["parent_asin"], rating_group(review["rating"]))
        bucket = self.groups.setdefault(key, {})
        bucket[row["source_record_sha256"]] = row
        if len(bucket) > self.per_group * 3:
            kept = sorted(bucket.values(), key=_order)[: self.per_group]
            self.groups[key] = {row["source_record_sha256"]: row for row in kept}

    def rows(self) -> list[dict]:
        return select_reviews(
            [row for bucket in self.groups.values() for row in bucket.values()],
            self.per_group,
        )


def trim_sample(state: dict, per_group: int) -> dict:
    """Keep the top reviews per rating group of a complete scan, as compact rows.

    Release files drop the decoded `original` record: loaders rebuild it from
    the source line in batches, so a restore never holds every decoded review.
    """
    if per_group < 1 or per_group > state["reviews_per_rating_group"]:
        raise ValueError(
            f"Review trim rule: {per_group} must be between 1 and the scanned {state['reviews_per_rating_group']} per rating group; rescan for a larger sample."
        )
    if not state.get("complete_source_scan"):
        raise ValueError(
            "Review trim rule: only a complete scan can be trimmed; finish the scan first."
        )
    rows = [expand_review(row) for row in state["reviews"]]
    trimmed = dict(state)
    kept = select_reviews(rows, per_group)
    trimmed["reviews"] = [compact_review(row) for row in kept]
    trimmed["coverage"] = coverage_of(kept, state["coverage"])
    trimmed["trimmed_from_reviews_per_rating_group"] = state["reviews_per_rating_group"]
    trimmed["reviews_per_rating_group"] = per_group
    return trimmed


def consume_range(
    data: bytes,
    start: int,
    *,
    final: bool,
    parents: set[str],
    rejected: list[int] | None = None,
) -> tuple[list[dict], int, int]:
    """Consume complete JSONL rows; the caller carries an unfinished tail forward.

    A selected row whose shape fails `review_record` is skipped and its byte
    offset appended to `rejected`, so one malformed source line cannot abort a
    whole-file scan and the count stays auditable in the checkpoint.
    """
    used = len(data) if final else data.rfind(b"\n") + 1
    if not used:
        raise ValueError(
            f"Review boundary rule: no complete row at byte {start}; fetch a larger source range."
        )
    found, count, offset = [], 0, 0
    while offset < used:
        newline = data.find(b"\n", offset, used)
        stop = used if newline < 0 else newline + 1
        line = data[offset:stop]
        count += 1
        match = PARENT_PATTERN.search(line)
        if match and match.group(1).decode("ascii") in parents:
            try:
                raw = json.loads(line)
                if isinstance(raw.get("text"), str) and raw["text"].strip():
                    found.append(review_record(line, start + offset))
            except ValueError:
                if rejected is None:
                    raise
                rejected.append(start + offset)
        offset = stop
    return found, used, count


def fetch_range(source: dict, start: int, end: int) -> bytes:
    for attempt in range(8):
        try:
            request = urllib.request.Request(
                source["url"] + f"?download=true&range_start={start}&range_end={end}",
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "Mosaic-review-evidence/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
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
        except (OSError, urllib.error.URLError, ValueError):
            if attempt == 7:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def coverage_of(rows: list[dict], parents) -> dict[str, int]:
    """Reviews kept per selected parent, counted once per row."""
    counts = Counter(row["original"]["parent_asin"] for row in rows)
    return {parent: counts.get(parent, 0) for parent in sorted(parents)}


def _checkpoint(
    path: Path, state: dict, sample: BoundedSample, parents: set[str]
) -> None:
    state["reviews"] = sample.rows()
    state["coverage"] = coverage_of(state["reviews"], parents)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False) + "\n")
    temporary.replace(path)


def fetch(
    category: str,
    destination: Path,
    parents: set[str],
    scan_bytes: int,
    per_group: int,
    workers: int = 4,
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
    sample = BoundedSample(per_group, state["reviews"])
    stop = min(source["bytes"], state["next_byte"] + scan_bytes)
    plan = []
    cursor = state["next_byte"]
    while cursor < stop:
        plan.append((cursor, min(stop, cursor + RANGE_BYTES) - 1))
        cursor += RANGE_BYTES
    started = time.monotonic()
    since_checkpoint = 0
    # A scan that starts at byte 0 hashes the whole file in order; a resumed
    # scan cannot, and stays unverified until a fresh whole-file scan.
    digest = hashlib.sha256() if state["next_byte"] == 0 else None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        window: deque = deque()
        upcoming = iter(plan)
        for item in upcoming:
            window.append((item, pool.submit(fetch_range, source, *item)))
            if len(window) >= workers * 2:
                break
        tail = b""
        while window:
            (start, end), future = window.popleft()
            for nxt in upcoming:
                window.append((nxt, pool.submit(fetch_range, source, *nxt)))
                break
            fetched = future.result()
            if digest is not None:
                digest.update(fetched)
            # Planned ranges end on fixed byte boundaries, so the unfinished
            # row at the end of one range is completed by the next one.
            data = tail + fetched
            base = start - len(tail)
            if b"\n" not in data and end + 1 == stop and stop < source["bytes"]:
                break
            rejected: list[int] = []
            found, used, count = consume_range(
                data,
                base,
                final=end + 1 == source["bytes"],
                parents=parents,
                rejected=rejected,
            )
            state["records_rejected"] = state.get("records_rejected", 0) + len(rejected)
            state["rejected_offsets"] = (state.get("rejected_offsets") or [])[
                :20
            ] + rejected[: max(0, 20 - len(state.get("rejected_offsets") or []))]
            tail = data[used:]
            for row in found:
                sample.add(row)
            state["next_byte"] = base + used
            state["records_scanned"] += count
            state["ranges"].append(
                {
                    "start": start,
                    "end": end,
                    "sha256": hashlib.sha256(fetched).hexdigest(),
                }
            )
            state["complete_source_scan"] = state["next_byte"] == source["bytes"]
            since_checkpoint += 1
            if since_checkpoint >= CHECKPOINT_RANGES or state["complete_source_scan"]:
                _checkpoint(path, state, sample, parents)
                since_checkpoint = 0
                print(
                    json.dumps(
                        {
                            "category": category,
                            "bytes_scanned": state["next_byte"],
                            "records_scanned": state["records_scanned"],
                            "reviews": len(state["reviews"]),
                            "products_with_reviews": sum(
                                1 for v in state["coverage"].values() if v
                            ),
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
            if end + 1 == stop:
                break
    if digest is not None and state["complete_source_scan"]:
        state["source_sha256_observed"] = digest.hexdigest()
        pinned = source["sha256"]
        if pinned is not None and state["source_sha256_observed"] != pinned:
            _checkpoint(path, state, sample, parents)
            raise ValueError(
                f"Source hash rule: {category} review file hashed "
                f"{state['source_sha256_observed']}, not the pinned {pinned}; "
                "re-pin only after confirming the source revision."
            )
        state["full_source_hash_verified"] = pinned is not None
    _checkpoint(path, state, sample, parents)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=REVIEW_SOURCES)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--examples", type=Path, default=ROOT / "data/real-catalog-examples.json"
    )
    parser.add_argument(
        "--parents",
        type=Path,
        help="JSON object mapping review category to parent ASINs; replaces --examples",
    )
    parser.add_argument("--scan-mib", type=int, default=256)
    parser.add_argument("--reviews-per-rating-group", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--trim-from",
        type=Path,
        help="a complete scan to trim to --reviews-per-rating-group instead of scanning",
    )
    args = parser.parse_args()
    if args.trim_from:
        trimmed = trim_sample(
            json.loads(args.trim_from.read_text()), args.reviews_per_rating_group
        )
        args.destination.mkdir(parents=True, exist_ok=True)
        target = args.destination / f"{args.category}-reviews.json"
        if target.resolve() == args.trim_from.resolve():
            raise ValueError(
                "Review trim rule: write the trimmed sample to another directory; the scan stays as scanned."
            )
        target.write_text(json.dumps(trimmed, ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {
                    "category": args.category,
                    "reviews": len(trimmed["reviews"]),
                    "products_with_reviews": sum(
                        1 for v in trimmed["coverage"].values() if v
                    ),
                    "reviews_per_rating_group": args.reviews_per_rating_group,
                }
            )
        )
        return
    if args.parents:
        parents = set(json.loads(args.parents.read_text())[args.category])
    else:
        examples = json.loads(args.examples.read_text())["examples"]
        parents = {
            row["product_id"]
            for row in examples
            if row.get("selected_in_bulk")
            and row.get("source_department") == args.category
        }
    fetch(
        args.category,
        args.destination,
        parents,
        args.scan_mib * 1024 * 1024,
        args.reviews_per_rating_group,
        args.workers,
    )


if __name__ == "__main__":
    main()
