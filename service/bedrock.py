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


# How each Claude 5-family model runs a single-decision route without thinking.
# Sonnet 5.5 rejects "disabled" with a 400 and names "between_tools" as its
# lowest setting, accepted at its default effort (measured 20 October 2026).
_THINKING_OFF = (
    ("anthropic.claude-sonnet-5-5", "between_tools"),
    ("anthropic.claude-sonnet-5", "disabled"),
    ("anthropic.claude-opus-5", "disabled"),
)
# These reject a forced toolChoice ("tool" or "any") with a 400.
_AUTO_TOOL_CHOICE_ONLY = ("anthropic.claude-sonnet-5-5", "anthropic.claude-opus-5-5")


def thinking_off_fields(model_id: str) -> dict[str, Any]:
    """The Converse additionalModelRequestFields that turn thinking off, if needed.

    Args:
        model_id: Bedrock model or inference profile ID.

    Returns:
        ``{"thinking": {...}}`` for a model that thinks by default, else ``{}``.
    """
    model = model_id.lower()
    for suffix, thinking_type in _THINKING_OFF:
        if model.endswith(suffix):
            return {"thinking": {"type": thinking_type}}
    return {}


def accepts_forced_tool_choice(model_id: str) -> bool:
    """Whether Converse may force a named tool for this model."""
    return not model_id.lower().endswith(_AUTO_TOOL_CHOICE_ONLY)
