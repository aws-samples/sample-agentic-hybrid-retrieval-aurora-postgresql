"""Bounded HTTP client for the canonical catalog API."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import httpx


class CatalogApiError(RuntimeError):
    """A sanitized catalog API boundary failure."""


class CatalogApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("CATALOG_API_URL") or "http://127.0.0.1:8000/api"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("CATALOG_API_TIMEOUT_SECONDS", "30")
        )
        self.transport = transport
        # The same shared origin secret nginx forwards for a workshop request
        # (see deploy/mosaic-bootstrap.sh). This adapter runs on the Code
        # Editor host as a trusted local process with its own filesystem
        # access to the generated `.env`, so it presents the secret directly
        # rather than needing a bypass; a deployment without it configured
        # simply sends no header, matching this client's behavior before the
        # API required one.
        self.origin_secret = os.getenv("MOSAIC_ORIGIN_VERIFY_SECRET")

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"User-Agent": "mosaic-retrieval-mcp/0.2.0"}
        if self.origin_secret:
            headers["X-Mosaic-Origin-Verify"] = self.origin_secret
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
                headers=headers,
            ) as client:
                response = client.request(method, path, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as error:
            raise CatalogApiError(
                f"Catalog API returned HTTP {error.response.status_code} "
                f"for {method} {path}."
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise CatalogApiError(
                f"Catalog API request failed for {method} {path}: "
                f"{type(error).__name__}."
            ) from error
        if not isinstance(body, dict):
            raise CatalogApiError(
                f"Catalog API returned a non-object response for {method} {path}."
            )
        return body


@lru_cache(maxsize=1)
def get_api_client() -> CatalogApiClient:
    return CatalogApiClient()
