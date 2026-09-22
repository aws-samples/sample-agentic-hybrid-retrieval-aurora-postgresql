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


def iter_records(directory: Path):
    """Decode lines across range boundaries only after complete-source verification."""
    source = json.loads((directory / "source.json").read_text())
    if source not in [source_identity(category) for category in SOURCES]:
        raise ValueError(
            "Source identity rule: metadata does not match a pinned release; "
            "restore the original source markers and ranges."
        )
    if (
        not (directory / "verified.json").exists()
        or json.loads((directory / "verified.json").read_text()) != source
    ):
        raise ValueError(
            "Verified source rule: complete-source checksum proof is missing; finish the download first."
        )
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=tuple(SOURCES))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--reserve-gib", type=int, default=5)
    args = parser.parse_args()
    if args.reserve_gib < 1:
        parser.error("--reserve-gib must leave at least 1 GiB free.")
    fetch(args.category, args.destination, args.reserve_gib * 1024**3)


if __name__ == "__main__":
    main()
