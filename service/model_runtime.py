"""Safe Bedrock readiness and error classification shared by API surfaces."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

_AUTHENTICATION_CODES = {
    "AccessDeniedException",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
}


class ModelRuntimeError(RuntimeError):
    """A safe, actionable failure from the configured model runtime."""


def _causes(error: BaseException) -> Iterator[BaseException]:
    """Yield an exception and its explicit causal chain once each."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def model_error_code(error: BaseException) -> str | None:
    """Return a Bedrock or credential error code without exposing request data."""
    for cause in _causes(error):
        if isinstance(cause, ClientError):
            return str(cause.response.get("Error", {}).get("Code", "BedrockError"))
        if isinstance(cause, BotoCoreError):
            return type(cause).__name__
        text = str(cause)
        for code in _AUTHENTICATION_CODES:
            if code in text:
                return code
    return None


def model_runtime_error(error: BaseException) -> ModelRuntimeError | None:
    """Convert a model-runtime failure into a bounded participant-facing error."""
    if isinstance(error, ModelRuntimeError):
        return error
    code = model_error_code(error)
    if code is None:
        return None
    if code in _AUTHENTICATION_CODES:
        return ModelRuntimeError(
            f"Amazon Bedrock credentials are unavailable ({code}). "
            "Refresh the active AWS session and restart the API process."
        )
    return ModelRuntimeError(f"Amazon Bedrock request failed: {code}")


def bedrock_credentials_status(region: str) -> dict[str, Any]:
    """Verify that this process can authenticate to AWS without invoking a model."""
    try:
        boto3.client("sts", region_name=region).get_caller_identity()
    except Exception as error:
        classified = model_runtime_error(error)
        return {
            "ready": False,
            "error": str(classified or "AWS credential validation failed"),
        }
    return {"ready": True}
