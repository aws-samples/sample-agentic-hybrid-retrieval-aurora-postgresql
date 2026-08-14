"""Shared Amazon Bedrock clients with bounded adaptive retries."""

from __future__ import annotations

import threading
from typing import Any

from botocore.config import Config

from service.config import get_settings

_clients: dict[tuple[str, str], Any] = {}
_lock = threading.Lock()


def client_config() -> Config:
    settings = get_settings()
    return Config(
        retries={
            "total_max_attempts": settings.bedrock_max_attempts,
            "mode": "adaptive",
        },
        connect_timeout=5,
        read_timeout=60,
        max_pool_connections=50,
    )


def get_bedrock_client(service_name: str, region: str | None = None):
    import boto3

    resolved_region = region or get_settings().aws_region
    key = (service_name, resolved_region)
    client = _clients.get(key)
    if client is not None:
        return client
    with _lock:
        client = _clients.get(key)
        if client is None:
            client = boto3.client(
                service_name,
                region_name=resolved_region,
                config=client_config(),
            )
            _clients[key] = client
    return client
