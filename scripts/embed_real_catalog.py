#!/usr/bin/env python3
"""Embed a verified real-product selection without modifying the live catalog.

Each completed batch is saved atomically with its source identities, input
hashes and model settings. A restart reuses only fully validated batches.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import math
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any

import numpy as np
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.embed_catalog import COHERE_EMBED_V4_DIMENSIONS, COHERE_EMBED_V4_MODEL_ID
from scripts.prepare_real_catalog import canonical, embedding_text, sha256
from service.embeddings import _cohere_request, _extract_embeddings

BATCH_PRODUCTS = 64
BATCH_CHARACTERS = 100_000
US_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


@dataclass
class TokenReservation:
    tokens: int
    completed_at: float | None = None


class TokenPacer:
    """Pace one Region, optionally learning text sizes from successful responses."""

    def __init__(self, tokens_per_minute: int, *, adaptive: bool = False):
        self.tokens_per_minute = tokens_per_minute
        self.adaptive = adaptive
        self.next_request_at = 0.0
        self.lock = threading.Lock()
        self.samples = deque(maxlen=64)
        self.reservations: list[TokenReservation] = []
        self.retry_attempts = 0

    def learn(self, characters: int, tokens: int | None) -> None:
        """Learn from verified cache or responses without charging historic usage."""
        if self.adaptive and characters > 0 and tokens is not None and tokens > 0:
            with self.lock:
                self.samples.append((characters, tokens))

    def _tokens_per_character(self) -> float:
        if len(self.samples) < 8:
            return 1 / 3
        average = sum(tokens for _, tokens in self.samples) / sum(
            characters for characters, _ in self.samples
        )
        recent_peak = max(
            tokens / characters for characters, tokens in list(self.samples)[-4:]
        )
        return max(1 / 6, average * 1.05, recent_peak)

    def delay_for(self, characters: int, now: float) -> float:
        with self.lock:
            start = max(now, self.next_request_at)
            # The pilot used about four characters per input token. Three leaves
            # room for less compact listings; Bedrock still enforces actual usage.
            self.next_request_at = start + characters / 3 / self.tokens_per_minute * 60
            return start - now

    def reserve(
        self, characters: int, now: float
    ) -> tuple[float, TokenReservation | None]:
        """Admit one request only when spacing and the rolling budget allow it."""
        with self.lock:
            self.reservations = [
                item
                for item in self.reservations
                if item.completed_at is None or item.completed_at > now - 60
            ]
            estimate = max(1, math.ceil(characters * self._tokens_per_character()))
            if estimate > self.tokens_per_minute:
                raise ValueError(
                    f"Embedding batch budget rule: estimated tokens={estimate}, "
                    f"job budget={self.tokens_per_minute}; increase the per-Region budget "
                    "within its applied quota before using adaptive pacing."
                )
            delay = max(0.0, self.next_request_at - now)
            if (
                sum(item.tokens for item in self.reservations) + estimate
                > self.tokens_per_minute
            ):
                expirations = [
                    item.completed_at + 60 - now
                    for item in self.reservations
                    if item.completed_at is not None
                ]
                delay = max(delay, min(expirations, default=1.0))
            if delay > 0:
                return delay, None
            reservation = TokenReservation(estimate)
            self.reservations.append(reservation)
            self.next_request_at = now + estimate / self.tokens_per_minute * 60
            return 0.0, reservation

    def acquire(self, characters: int) -> TokenReservation | None:
        if self.adaptive:
            while True:
                delay, reservation = self.reserve(characters, time.monotonic())
                if reservation is not None:
                    return reservation
                time.sleep(min(delay, 1.0))
        remaining = self.delay_for(characters, time.monotonic())
        while remaining > 0:
            pause = min(remaining, 30)
            time.sleep(pause)
            remaining -= pause
        return None

    def complete(
        self,
        reservation: TokenReservation | None,
        tokens: int | None,
        *,
        retry_attempts: int = 0,
        now: float | None = None,
    ) -> None:
        """Reconcile actual usage, reserving a full request for each reported retry."""
        if reservation is None:
            return
        finished = time.monotonic() if now is None else now
        with self.lock:
            estimated = reservation.tokens
            actual = tokens if tokens is not None else estimated
            reservation.tokens = actual + retry_attempts * max(actual, estimated)
            reservation.completed_at = finished
            self.retry_attempts += retry_attempts
            debt = max(0, reservation.tokens - estimated)
            self.next_request_at += debt / self.tokens_per_minute * 60

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "strategy": "measured" if self.adaptive else "conservative",
                "samples": len(self.samples),
                "estimated_tokens_per_character": round(
                    self._tokens_per_character(), 6
                ),
                "reported_retry_attempts": self.retry_attempts,
            }

    def set_budget(self, tokens_per_minute: int) -> None:
        with self.lock:
            self.tokens_per_minute = tokens_per_minute


@dataclass
class RegionTarget:
    """An independent source-Region quota and client for the same US model."""

    region: str
    client: Any
    pacer: TokenPacer
    applied_tokens_per_minute: int
    quotas: Any = None


def validate_regions(regions: tuple[str, ...], workers: int) -> None:
    if (
        not regions
        or len(set(regions)) != len(regions)
        or set(regions) - set(US_REGIONS)
    ):
        raise ValueError(
            f"Embedding Region rule: regions={regions!r}; choose distinct Regions from "
            f"{US_REGIONS!r} to retain the existing US processing boundary."
        )
    if not len(regions) <= workers <= 16:
        raise ValueError(
            f"Embedding worker rule: workers={workers}, regions={len(regions)}; "
            "use at least one worker per Region and at most 16 total."
        )


def validate_profile(region: str, profile: dict) -> None:
    """Refuse model or geography changes before any additional paid requests."""
    model = COHERE_EMBED_V4_MODEL_ID.removeprefix("us.")
    expected = {
        f"arn:aws:bedrock:{destination}::foundation-model/{model}"
        for destination in US_REGIONS
    }
    actual = {entry.get("modelArn") for entry in profile.get("models", [])}
    if (
        profile.get("status") != "ACTIVE"
        or profile.get("inferenceProfileId") != COHERE_EMBED_V4_MODEL_ID
        or actual != expected
    ):
        raise ValueError(
            f"Embedding profile rule: {region} returned status={profile.get('status')!r}, "
            f"id={profile.get('inferenceProfileId')!r}, models={actual!r}; "
            "use the active Cohere Embed v4 US profile with the verified US destinations."
        )


def regional_targets(
    regions, workers, tokens_per_minute, adaptive_pacing=False
) -> list[RegionTarget]:
    """Read each source Region's applied quota before constructing its paced client."""
    import boto3
    from botocore.config import Config

    validate_regions(regions, workers)
    targets = []
    for region in regions:
        profile = boto3.client("bedrock", region_name=region).get_inference_profile(
            inferenceProfileIdentifier=COHERE_EMBED_V4_MODEL_ID
        )
        validate_profile(region, profile)
        quotas = boto3.client("service-quotas", region_name=region)
        applied = applied_quota(quotas)
        pacer = TokenPacer(
            throughput_budget(applied, tokens_per_minute), adaptive=adaptive_pacing
        )
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=10,
                read_timeout=180,
                max_pool_connections=workers + 2,
                retries={"total_max_attempts": 10, "mode": "adaptive"},
            ),
        )
        targets.append(
            RegionTarget(
                region,
                client,
                pacer,
                applied,
                quotas if tokens_per_minute is None else None,
            )
        )
    return targets


def verified_selection(directory: Path) -> dict:
    """Check the complete selected file before making any paid model calls."""
    manifest = json.loads((directory / "selection.json").read_text())
    expected = manifest.get("products")
    if type(expected) is not int or expected < 1:
        raise ValueError(
            f"Selection count rule: products={expected!r}; restore a nonempty verified selection."
        )
    with (directory / "catalog.jsonl.gz").open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != manifest.get("catalog_sha256"):
        raise ValueError(
            f"Selection hash rule: found {actual}; expected {manifest.get('catalog_sha256')}. "
            "Restore the verified selection before embedding."
        )
    return manifest


def iter_batches(directory: Path):
    """Yield bounded batches while checking that text matches its unchanged source."""
    batch = []
    characters = 0
    with gzip.open(directory / "catalog.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            text = row["embedding_text"]
            if (
                row["source_record_sha256"] != sha256(canonical(row["original"]))
                or row["embedding_text_sha256"] != sha256(text)
                or text != embedding_text(row["original"])
            ):
                raise ValueError(
                    f"Source text rule: {row['parent_asin']} differs from its source or hash; "
                    "rebuild the selection rather than embedding altered text."
                )
            if batch and (
                len(batch) >= BATCH_PRODUCTS
                or characters + len(text) > BATCH_CHARACTERS
            ):
                yield batch
                batch = []
                characters = 0
            batch.append(row)
            characters += len(text)
    if batch:
        yield batch


def batch_identity(rows: list[dict]) -> dict:
    return {
        "model_id": COHERE_EMBED_V4_MODEL_ID,
        "dimensions": COHERE_EMBED_V4_DIMENSIONS,
        "input_type": "search_document",
        "products": [row["parent_asin"] for row in rows],
        "text_sha256": [row["embedding_text_sha256"] for row in rows],
    }


def validate_vectors(values, count: int) -> np.ndarray:
    """Refuse incomplete, non-finite, zero or incompatible model output."""
    vectors = np.asarray(values, dtype=np.float32)
    expected = (count, COHERE_EMBED_V4_DIMENSIONS)
    if vectors.shape != expected or not np.isfinite(vectors).all():
        raise ValueError(
            f"Embedding shape rule: found {vectors.shape}; expected {expected} finite values. "
            "Do not load this batch; inspect the model response."
        )
    if (np.linalg.norm(vectors, axis=1) == 0).any():
        raise ValueError(
            "Embedding norm rule: zero vector; do not cache or load the batch."
        )
    return vectors


def load_batch(path: Path, expected: dict) -> tuple[np.ndarray, dict]:
    """Validate cache identity and vector bytes before treating a batch as complete."""
    with np.load(path, allow_pickle=False) as cached:
        metadata = json.loads(str(cached["metadata"].item()))
        if metadata.get("identity") != expected:
            raise ValueError(
                f"Embedding cache rule: {path.name} has different products or model settings; "
                "restore the matching cache or use a new destination."
            )
        vectors = validate_vectors(cached["vectors"], len(expected["products"]))
        actual = hashlib.sha256(vectors.tobytes()).hexdigest()
        if actual != metadata.get("vector_sha256"):
            raise ValueError(
                f"Embedding cache rule: {path.name} vector hash differs; restore that batch."
            )
        return vectors, metadata


def input_tokens(response: dict, payload: dict) -> int | None:
    headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    value = headers.get("x-amzn-bedrock-input-token-count")
    if value is None:
        value = payload.get("meta", {}).get("billed_units", {}).get("input_tokens")
    if value is None:
        return None
    count = int(value)
    if count < 0:
        raise ValueError(
            "Token accounting rule: negative model usage; inspect the response."
        )
    return count


def process_batch(
    rows: list[dict],
    output: Path,
    client,
    pacer: TokenPacer | None = None,
    region: str | None = None,
) -> dict:
    """Reuse verified work, otherwise call the production embedding request format."""
    identity = batch_identity(rows)
    key = sha256(canonical(identity))
    path = output / f"{key}.npz"
    if path.exists():
        _, metadata = load_batch(path, identity)
        if pacer is not None:
            pacer.learn(
                sum(len(row["embedding_text"]) for row in rows),
                metadata["input_tokens"],
            )
        return {**metadata, "reused": True}
    characters = sum(len(row["embedding_text"]) for row in rows)
    reservation = pacer.acquire(characters) if pacer is not None else None
    started = time.monotonic()
    request_started_at = time.time()
    response = client.invoke_model(
        modelId=COHERE_EMBED_V4_MODEL_ID,
        body=json.dumps(
            _cohere_request(
                [row["embedding_text"] for row in rows],
                COHERE_EMBED_V4_DIMENSIONS,
                "search_document",
            )
        ),
        accept="application/json",
        contentType="application/json",
    )
    try:
        payload = json.loads(response["body"].read())
    finally:
        response["body"].close()
    tokens = input_tokens(response, payload)
    retry_attempts = int(response.get("ResponseMetadata", {}).get("RetryAttempts", 0))
    if pacer is not None:
        pacer.complete(reservation, tokens, retry_attempts=retry_attempts)
        pacer.learn(characters, tokens)
    vectors = validate_vectors(_extract_embeddings(payload), len(rows))
    metadata = {
        "identity": identity,
        "vector_sha256": hashlib.sha256(vectors.tobytes()).hexdigest(),
        "input_tokens": tokens,
        "input_characters": characters,
        "request_started_at": request_started_at,
        "request_completed_at": time.time(),
        "retry_attempts": retry_attempts,
        "request_id": response.get("ResponseMetadata", {}).get("RequestId"),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    if region is not None:
        metadata["request_region"] = region
    temporary = path.with_suffix(".partial")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, vectors=vectors, metadata=canonical(metadata))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {**metadata, "reused": False}


def applied_quota(quotas) -> int:
    """Read the applied limit; a requested increase is not usable throughput."""
    return int(
        quotas.get_service_quota(ServiceCode="bedrock", QuotaCode="L-4C3F0FE6")[
            "Quota"
        ]["Value"]
    )


def throughput_budget(applied: int, requested: int | None) -> int:
    allocation = requested if requested is not None else int(applied * 0.85)
    if not 1 <= allocation <= applied:
        raise ValueError(
            f"Embedding throughput rule: job budget {allocation}, applied quota {applied}; "
            "choose a positive budget within the current quota."
        )
    return allocation


def refresh_budget(target: RegionTarget) -> None:
    """Adopt an applied quota change, retaining the last limit on API failure."""
    if target.quotas is None:
        return
    try:
        current = applied_quota(target.quotas)
        allocation = throughput_budget(current, None)
    except (BotoCoreError, ClientError) as error:
        print(
            json.dumps(
                {
                    "quota_refresh": type(error).__name__,
                    "region": target.region,
                    "action": "retaining the last verified throughput budget",
                }
            ),
            flush=True,
        )
        return
    target.pacer.set_budget(allocation)
    target.applied_tokens_per_minute = current


def report_budgets(targets: list[RegionTarget], report: dict) -> None:
    report["source_regions"] = [target.region for target in targets]
    report["applied_tokens_per_minute_by_region"] = {
        target.region: target.applied_tokens_per_minute for target in targets
    }
    report["job_token_budget_per_minute_by_region"] = {
        target.region: target.pacer.tokens_per_minute for target in targets
    }
    report["job_token_budget_per_minute"] = sum(
        target.pacer.tokens_per_minute for target in targets
    )
    # Preserve the single-Region report field without presenting summed capacity
    # as approval of an account-wide quota increase.
    report["applied_account_tokens_per_minute"] = (
        targets[0].applied_tokens_per_minute if len(targets) == 1 else None
    )
    report["quota_scope"] = "Per model, per source Region; independently paced."


def count_result(report: dict, result: dict) -> None:
    count = len(result["identity"]["products"])
    report["products"] += count
    report["reused_products" if result["reused"] else "newly_embedded"] += count
    report["batches"] += 1
    if not result["reused"] and result.get("request_region"):
        by_region = report.setdefault("newly_embedded_by_region", {})
        region = result["request_region"]
        by_region[region] = by_region.get(region, 0) + count
    if result["input_tokens"] is None:
        report["batches_without_token_usage"] += 1
    else:
        report["input_tokens"] += result["input_tokens"]
        if not result["reused"]:
            report["new_input_tokens"] += result["input_tokens"]


def save_report(path: Path, report: dict) -> None:
    """Publish a complete status document, including after the final batch."""
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def embed_batches(directory, workers, max_batches, targets, report) -> None:
    """Keep at most `workers` paid calls in flight and checkpoint each completion."""
    started = time.monotonic()
    quota_checked_at = started

    available = deque(targets[index % len(targets)] for index in range(workers))
    pending = {}

    def collect():
        nonlocal quota_checked_at
        finished, _ = wait(pending, return_when=FIRST_COMPLETED)
        for future in finished:
            count_result(report, future.result())
            available.append(pending.pop(future))
        now = time.monotonic()
        report["elapsed_seconds"] = round(now - started)
        report["pacing_by_region"] = {
            target.region: target.pacer.snapshot() for target in targets
        }
        if now - quota_checked_at >= 300:
            for target in targets:
                refresh_budget(target)
            report_budgets(targets, report)
            quota_checked_at = now
        save_report(directory / "embedding-progress.json", report)
        if report["batches"] % 20 < len(finished):
            print(json.dumps(report), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in islice(iter_batches(directory), max_batches):
            target = available.popleft()
            future = pool.submit(
                process_batch,
                rows,
                directory / "embeddings",
                target.client,
                target.pacer,
                target.region,
            )
            pending[future] = target
            if len(pending) >= workers:
                collect()
        while pending:
            collect()


def run(
    directory: Path,
    *,
    workers: int,
    max_batches: int | None,
    tokens_per_minute: int | None = None,
    regions: tuple[str, ...] = ("us-east-1",),
    adaptive_pacing: bool = False,
) -> dict:
    """Checkpoint bounded calls without changing the live catalog.

    Args:
        directory: Verified selection directory and destination for its cache.
        workers: Maximum number of simultaneous Bedrock requests.
        max_batches: Optional pilot cap; omit to complete the full selection.
        tokens_per_minute: Optional per-Region budget below its applied quota.
            Otherwise reserve 15 percent and refresh the quota every five minutes.
        regions: Distinct US source Regions, each with its own quota and pacer.
        adaptive_pacing: Learn token estimates and reconcile rolling usage per Region.

    Returns:
        Counts for the completed pass, with an explicit completeness flag.
    """
    selection = verified_selection(directory)
    output = directory / "embeddings"
    output.mkdir(exist_ok=True)
    targets = regional_targets(regions, workers, tokens_per_minute, adaptive_pacing)
    report = {
        "catalog_sha256": selection["catalog_sha256"],
        "model_id": COHERE_EMBED_V4_MODEL_ID,
        "dimensions": COHERE_EMBED_V4_DIMENSIONS,
        "products": 0,
        "newly_embedded": 0,
        "reused_products": 0,
        "input_tokens": 0,
        "new_input_tokens": 0,
        "batches_without_token_usage": 0,
        "batches": 0,
        "complete": False,
        "token_usage_scope": (
            "Successful saved responses only; failed or lost requests may also be billed."
        ),
    }
    report_budgets(targets, report)
    with (output / ".writer.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "Embedding writer rule: another process owns this cache; reuse its progress."
            ) from None
        started = time.monotonic()
        embed_batches(
            directory,
            workers,
            max_batches,
            targets,
            report,
        )
        report["complete"] = report["products"] == selection["products"]
        if not report["complete"] and max_batches is None:
            raise ValueError(
                f"Embedding completeness rule: {report['products']} of {selection['products']} "
                "products; finish embedding before promoting the catalog."
            )
        report["elapsed_seconds"] = round(time.monotonic() - started)
        report["cache_bytes"] = sum(
            path.stat().st_size for path in output.glob("*.npz")
        )
        save_report(directory / "embedding-report.json", report)
        save_report(directory / "embedding-progress.json", report)
        print(json.dumps(report), flush=True)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--adaptive-pacing", action="store_true")
    parser.add_argument(
        "--tokens-per-minute", type=int, help="Budget per source Region."
    )
    parser.add_argument(
        "--regions", nargs="+", default=["us-east-1"], choices=US_REGIONS
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16.")
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be positive.")
    run(
        args.selection,
        workers=args.workers,
        max_batches=args.max_batches,
        tokens_per_minute=args.tokens_per_minute,
        regions=tuple(args.regions),
        adaptive_pacing=args.adaptive_pacing,
    )


if __name__ == "__main__":
    main()
