#!/usr/bin/env python3
"""Fetch pinned public metadata in verified, resumable compressed ranges.

Only source metadata is downloaded. This tool never downloads photographs,
opens a database, invokes a model or publishes workshop assets.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

REVISION = "2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e"
SOURCES = {
    "Electronics": (
        5_246_144_134,
        "5eb4dabd539586c49654297319ef178b62a2fe8e43108376feda125f04455d93",
    ),
    "Office_Products": (
        2_146_468_843,
        "d9709095587ee34b2d5e639ca69de2a6fc8ab1953c467b86715e409c5ad78314",
    ),
    "Home_and_Kitchen": (
        11_788_767_944,
        "691353084748d985180deb13dc8de59afe4969933ad3692ea06b80460510aa56",
    ),
}
CHUNK_BYTES = 32 * 1024 * 1024


def source_url(category: str) -> str:
    return (
        "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
        f"resolve/{REVISION}/raw/meta_categories/meta_{category}.jsonl"
    )


def source_identity(category: str) -> dict:
    size, digest = SOURCES[category]
    return {
        "source": source_url(category),
        "revision": REVISION,
        "bytes": size,
        "sha256": digest,
    }


def validate_range(
    status: int, content_range: str | None, start: int, end: int, total: int
) -> None:
    """Reject cached or full-file responses that do not match the requested bytes."""
    expected = f"bytes {start}-{end}/{total}"
    if status != 206 or content_range != expected:
        raise ValueError(
            f"Source range rule: got HTTP {status}, {content_range!r}; "
            f"expected 206, {expected!r}. Retry the pinned source range."
        )


def read_chunk(path: Path, expected_bytes: int) -> bytes:
    """Check the gzip checksum and byte count before reusing an earlier chunk."""
    with gzip.open(path, "rb") as stream:
        data = stream.read(expected_bytes + 1)
    if len(data) != expected_bytes:
        raise ValueError(
            f"Chunk length rule: {path.name} has {len(data)} bytes; expected {expected_bytes}."
        )
    return data


def fetch(category: str, destination: Path, min_free_bytes: int) -> None:
    """Resume verified ranges and check the full source hash before marking ready."""
    size, expected_digest = SOURCES[category]
    output = destination / category
    output.mkdir(parents=True, exist_ok=True)
    identity = source_identity(category)
    marker = output / "source.json"
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise ValueError(
            "Source identity rule: destination contains another source version; use a new directory."
        )
    marker.write_text(json.dumps(identity, indent=2) + "\n")
    digest = hashlib.sha256()
    started = time.monotonic()
    for number, start in enumerate(range(0, size, CHUNK_BYTES)):
        end = min(size, start + CHUNK_BYTES) - 1
        path = output / f"{number:05d}.jsonl.part.gz"
        if path.exists():
            data = read_chunk(path, end - start + 1)
        else:
            if shutil.disk_usage(output).free < min_free_bytes + CHUNK_BYTES:
                raise ValueError(
                    "Free space rule: reserve would be crossed; move the metadata destination to a larger disk."
                )
            for attempt in range(5):
                try:
                    request = urllib.request.Request(
                        source_url(category) + f"?download=true&range_start={start}",
                        headers={
                            "Range": f"bytes={start}-{end}",
                            "User-Agent": "Mosaic-catalog-assessment/1.0",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=60) as response:
                        validate_range(
                            response.status,
                            response.headers.get("Content-Range"),
                            start,
                            end,
                            size,
                        )
                        data = response.read(end - start + 2)
                    if len(data) != end - start + 1:
                        raise ValueError(
                            f"Source byte-count rule: range {number} is incomplete; retry that range."
                        )
                    break
                except (OSError, urllib.error.URLError):
                    if attempt == 4:
                        raise
                    time.sleep(min(2**attempt, 16))
            temporary = path.with_suffix(".partial")
            with gzip.open(temporary, "wb", compresslevel=1) as stream:
                stream.write(data)
            temporary.replace(path)
        digest.update(data)
        if number % 8 == 0 or end + 1 == size:
            print(
                json.dumps(
                    {
                        "source": category,
                        "bytes_checked": end + 1,
                        "total_bytes": size,
                        "elapsed_seconds": round(time.monotonic() - started),
                    }
                ),
                flush=True,
            )
    if digest.hexdigest() != expected_digest:
        raise ValueError(
            "Source hash rule: full metadata differs from its pinned SHA-256; do not select or embed records."
        )
    (output / "verified.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(
        json.dumps({"source": category, "verified": True, "sha256": expected_digest}),
        flush=True,
    )


def _fetch_range(category: str, start: int, end: int, size: int) -> bytes:
    """Fetch one verified byte range with bounded retries."""
    for attempt in range(8):
        try:
            request = urllib.request.Request(
                source_url(category) + f"?download=true&range_start={start}",
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "Mosaic-catalog-assessment/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                validate_range(
                    response.status,
                    response.headers.get("Content-Range"),
                    start,
                    end,
                    size,
                )
                data = response.read(end - start + 2)
            if len(data) != end - start + 1:
                raise ValueError(
                    f"Source byte-count rule: range at {start} is incomplete; retry that range."
                )
            return data
        except (OSError, urllib.error.URLError, ValueError):
            if attempt == 7:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def leaf_of(line: bytes) -> str | None:
    """Taxonomy leaf of a raw metadata line, without decoding the whole record."""
    marker = line.find(b'"categories": [')
    if marker < 0:
        return None
    close = line.find(b"]", marker)
    if close < 0:
        return None
    try:
        categories = json.loads(line[marker + 14 : close + 1])
    except ValueError:
        return None
    return categories[-1] if categories else None


def stream_filter(
    category: str,
    destination: Path,
    keep_parents: set[str],
    keep_leaves: set[str],
    workers: int = 5,
) -> dict:
    """Verify the whole pinned source in one ordered pass while keeping only wanted records.

    The raw dumps are larger than the disks this runs on, so this mode never
    stores them. Ranges are fetched by a small pool and consumed in order, the
    full-file SHA-256 is computed from every byte, and only lines whose parent
    ASIN is in `keep_parents` or whose taxonomy leaf is in `keep_leaves` are
    written. The filtered file is verified by its own hash in `verified.json`;
    `iter_records` reads it exactly like a complete download.
    """
    from concurrent.futures import ThreadPoolExecutor

    size, expected_digest = SOURCES[category]
    output = destination / category
    output.mkdir(parents=True, exist_ok=True)
    identity = source_identity(category)
    marker = output / "source.json"
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise ValueError(
            "Source identity rule: destination contains another source version; use a new directory."
        )
    marker.write_text(json.dumps(identity, indent=2) + "\n")
    ranges = [
        (start, min(size, start + CHUNK_BYTES) - 1)
        for start in range(0, size, CHUNK_BYTES)
    ]
    digest = hashlib.sha256()
    filtered = output / "filtered.jsonl.gz"
    temporary = filtered.with_suffix(".partial")
    kept = lines = 0
    pending = b""
    started = time.monotonic()
    from collections import deque

    def ordered_ranges(pool):
        """Yield (range, bytes) in order with a bounded prefetch window, so memory stays flat."""
        window: deque = deque()
        upcoming = iter(ranges)
        for item in upcoming:
            window.append(
                (item, pool.submit(_fetch_range, category, item[0], item[1], size))
            )
            if len(window) >= workers * 2:
                break
        while window:
            item, future = window.popleft()
            yield item, future.result()
            for nxt in upcoming:
                window.append(
                    (nxt, pool.submit(_fetch_range, category, nxt[0], nxt[1], size))
                )
                break

    with (
        gzip.open(temporary, "wb", compresslevel=1) as out,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        for number, ((start, end), data) in enumerate(ordered_ranges(pool)):
            digest.update(data)
            buffer = pending + data
            cut = buffer.rfind(b"\n")
            complete, pending = (
                (buffer[: cut + 1], buffer[cut + 1 :]) if cut >= 0 else (b"", buffer)
            )
            for line in complete.splitlines(keepends=True):
                if not line.strip():
                    continue
                lines += 1
                head = line.find(b'"parent_asin": "')
                parent = (
                    line[head + 16 : head + 26].decode("ascii", "replace")
                    if head >= 0
                    else None
                )
                if (parent in keep_parents) or (leaf_of(line) in keep_leaves):
                    out.write(line)
                    kept += 1
            if number % 8 == 0 or end + 1 == size:
                print(
                    json.dumps(
                        {
                            "source": category,
                            "bytes_checked": end + 1,
                            "total_bytes": size,
                            "lines": lines,
                            "kept": kept,
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
        if pending.strip():
            lines += 1
            head = pending.find(b'"parent_asin": "')
            parent = (
                pending[head + 16 : head + 26].decode("ascii", "replace")
                if head >= 0
                else None
            )
            if (parent in keep_parents) or (leaf_of(pending) in keep_leaves):
                out.write(pending + b"\n")
                kept += 1
    if digest.hexdigest() != expected_digest:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            "Source hash rule: full metadata differs from its pinned SHA-256; do not select or embed records."
        )
    temporary.replace(filtered)
    with filtered.open("rb") as stream:
        filtered_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    proof = {
        **identity,
        "filter": {
            "keep_parents": len(keep_parents),
            "keep_parents_sha256": hashlib.sha256(
                "\n".join(sorted(keep_parents)).encode()
            ).hexdigest(),
            "keep_leaves": sorted(keep_leaves),
            "lines": lines,
            "kept": kept,
            "filtered_sha256": filtered_digest,
        },
    }
    (output / "verified.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(
        json.dumps(
            {"source": category, "verified": True, "kept": kept, "lines": lines}
        ),
        flush=True,
    )
    return proof


def iter_records(directory: Path):
    """Decode lines across range boundaries only after complete-source verification."""
    source = json.loads((directory / "source.json").read_text())
    if source not in [source_identity(category) for category in SOURCES]:
        raise ValueError(
            "Source identity rule: metadata does not match a pinned release; "
            "restore the original source markers and ranges."
        )
    verified = (
        json.loads((directory / "verified.json").read_text())
        if (directory / "verified.json").exists()
        else None
    )
    if (
        verified is None
        or {k: v for k, v in verified.items() if k != "filter"} != source
    ):
        raise ValueError(
            "Verified source rule: complete-source checksum proof is missing; finish the download first."
        )
    if "filter" in verified:
        yield from _iter_filtered(directory, verified["filter"])
        return
    pending = b""
    digest = hashlib.sha256()
    count = 0
    for path in sorted(directory.glob("*.jsonl.part.gz")):
        with gzip.open(path, "rb") as stream:
            raw = stream.read()
        digest.update(raw)
        count += len(raw)
        lines = (pending + raw).split(b"\n")
        pending = lines.pop()
        for line in lines:
            if line.strip():
                yield json.loads(line)
    if pending.strip():
        yield json.loads(pending)
    if count != source["bytes"] or digest.hexdigest() != source["sha256"]:
        raise ValueError(
            "Verified source rule: stored ranges changed after download; discard the derived selection."
        )


def _iter_filtered(directory: Path, proof: dict):
    """Yield the filtered records after checking the filtered file's own hash."""
    path = directory / "filtered.jsonl.gz"
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != proof.get("filtered_sha256"):
        raise ValueError(
            "Verified source rule: filtered records changed after the stream; rerun the filtered fetch."
        )
    count = 0
    with gzip.open(path, "rb") as stream:
        for line in stream:
            if line.strip():
                count += 1
                yield json.loads(line)
    if count != proof.get("kept"):
        raise ValueError(
            f"Verified source rule: {count} filtered records, proof says {proof.get('kept')}; rerun the filtered fetch."
        )


def _read_list(path: Path) -> set[str]:
    return {
        line.split("\t")[0].strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=tuple(SOURCES))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--reserve-gib", type=int, default=5)
    parser.add_argument(
        "--keep-parents",
        type=Path,
        help="Stream mode: file of parent ASINs (first tab column) to keep",
    )
    parser.add_argument(
        "--keep-leaves",
        type=Path,
        help="Stream mode: file of taxonomy leaf names to keep, one per line",
    )
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    if args.reserve_gib < 1:
        parser.error("--reserve-gib must leave at least 1 GiB free.")
    if args.keep_parents or args.keep_leaves:
        stream_filter(
            args.category,
            args.destination,
            _read_list(args.keep_parents) if args.keep_parents else set(),
            _read_list(args.keep_leaves) if args.keep_leaves else set(),
            args.workers,
        )
        return
    fetch(args.category, args.destination, args.reserve_gib * 1024**3)


if __name__ == "__main__":
    main()
