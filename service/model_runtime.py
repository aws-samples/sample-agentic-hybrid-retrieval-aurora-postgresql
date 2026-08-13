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
_AUTHENTICATION_MESSAGES = {
    code: (
        f"Amazon Bedrock credentials are unavailable ({code}). "
        "Refresh the active AWS session and restart the API process."
    )
    for code in _AUTHENTICATION_CODES
}
_MODEL_REQUEST_FAILED = (
    "Amazon Bedrock request failed. Retry after checking model access and region."
)


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
    code = model_error_code(error)
    if code in _AUTHENTICATION_MESSAGES:
        return ModelRuntimeError(_AUTHENTICATION_MESSAGES[code])
    if code is not None or isinstance(error, ModelRuntimeError):
        return ModelRuntimeError(_MODEL_REQUEST_FAILED)
    return None


def safe_model_runtime_message(error: BaseException, *, fallback: str) -> str:
    """Return an allowlisted runtime message without serializing the exception."""
    classified = model_runtime_error(error)
    return str(classified) if classified is not None else fallback


def bedrock_credentials_status(region: str) -> dict[str, Any]:
    """Verify that this process can authenticate to AWS without invoking a model."""
    try:
        boto3.client("sts", region_name=region).get_caller_identity()
    except Exception as error:
        return {
            "ready": False,
            "error": safe_model_runtime_message(
                error,
                fallback=(
                    "AWS credential validation failed. Refresh the active AWS "
                    "session and restart the API process."
                ),
            ),
        }
    return {"ready": True}
