"""Shared Amazon Bedrock client construction with adaptive retries.

A workshop room drives many concurrent Bedrock calls (query embeddings and Cohere
Rerank) through one API process. Rebuilding a boto3 client per call re-runs
credential resolution and endpoint discovery every time, and the default retry
mode gives up quickly under the throttling a full room produces. This module hands
out per-(service, region) client singletons configured with botocore's adaptive
retry mode, which adds client-side rate limiting on top of the bounded attempt
count so bursts back off instead of failing.
"""
from __future__ import annotations

import threading
from typing import Any

from .config import get_settings

_clients: dict[tuple[str, str], Any] = {}
_lock = threading.Lock()


def _client_config():
    from botocore.config import Config

    settings = get_settings()
    return Config(
        retries={"max_attempts": settings.bedrock_max_attempts, "mode": "adaptive"},
    )


def get_bedrock_client(service_name: str, region: str | None = None):
    """Return a cached boto3 client for a Bedrock service, keyed by (service, region).

    Args:
        service_name: The boto3 service, e.g. "bedrock-runtime" (embeddings) or
            "bedrock-agent-runtime" (Cohere Rerank).
        region: AWS region; defaults to the configured aws_region.

    Returns:
        A boto3 client with adaptive retries, reused across calls in this process.
    """
    import boto3

    resolved_region = region or get_settings().aws_region
    key = (service_name, resolved_region)
    client = _clients.get(key)
    if client is not None:
        return client
    with _lock:
        client = _clients.get(key)
        if client is None:
            client = boto3.client(service_name, region_name=resolved_region, config=_client_config())
            _clients[key] = client
    return client


def bedrock_client_config():
    """The botocore Config (adaptive retries) for callers that build their own client."""
    return _client_config()
