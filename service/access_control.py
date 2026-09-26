"""Shared-secret caller trust and process-local admission control.

The API's only caller identity is a shared origin secret nginx forwards for
every request that actually reached it through CloudFront's configured origin
on the Code Editor host (see `deploy/mosaic-bootstrap.sh`, the nginx
`X-Mosaic-Origin-Verify` check). It authorizes protected work; it is not a
participant identity, and this deployment has no per-user accounting. A
request that reaches this process directly -- bypassing nginx -- or that
spoofs the header without knowing the secret must perform no protected work,
even if nginx's own check is ever misconfigured or skipped.

This module also holds the process-local admission control (active-run
concurrency and a request-rate budget) for routes that invoke a model or run
an expensive diagnostic. Both counters are scoped to this one uvicorn process.
The deployed topology runs exactly one `mosaic-api` process per attendee stack
with no `--workers`, so today that is the whole deployment's quota; it is not a
cross-process or cross-instance limit, and nothing here coordinates counters
across more than one process. Running this service with multiple workers would
need a shared store (Redis or similar) this deployment does not have.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from service.config import ConfigurationError, Settings, get_settings

#: The only unauthenticated route. Deliberately minimal: everything else in
#: this API needs the shared origin secret.
_PUBLIC_PATHS = frozenset({"/api/health"})

_ORIGIN_HEADER = "x-mosaic-origin-verify"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _client_is_loopback(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in _LOOPBACK_HOSTS


def assert_bootable(settings: Settings) -> None:
    """Refuse to start serving traffic on an unusable access configuration.

    Called from the ASGI lifespan (`service.main._lifespan`), which only runs
    when a real server actually starts accepting connections -- not when a
    script imports `service.main` to read its routes. A deployment that asked
    for origin verification and configured no secret must fail closed here,
    before it looks like a healthy, listening process.
    """
    if settings.require_origin_verification and not settings.origin_verify_secret:
        raise ConfigurationError(
            "MOSAIC_REQUIRE_ORIGIN_VERIFICATION is true but "
            "MOSAIC_ORIGIN_VERIFY_SECRET is not set; found no shared origin "
            "secret to verify callers against; fix: set "
            "MOSAIC_ORIGIN_VERIFY_SECRET to the value nginx forwards as "
            "X-Mosaic-Origin-Verify, or set "
            "MOSAIC_REQUIRE_ORIGIN_VERIFICATION=false only for loopback-only "
            "local development -- never in a reachable deployment."
        )


def verify_origin_access(request: Request) -> None:
    """Enforce the shared workshop origin secret on every protected route.

    Applied as a FastAPI app-level dependency (see `service.main`), so it runs
    for every route registered on the app, including ones added later, without
    each route decorator having to remember it. `/api/health` is the one
    documented exception.

    Raises:
        HTTPException: 401 when verification is required and the presented
            header is missing or does not match; 403 when this deployment runs
            its explicit, loopback-only development bypass and the request did
            not originate on the loopback interface.
    """
    if request.url.path in _PUBLIC_PATHS:
        return
    settings = get_settings()
    if not settings.require_origin_verification:
        if _client_is_loopback(request):
            return
        raise HTTPException(
            403,
            "This deployment runs without the workshop origin secret "
            "(MOSAIC_REQUIRE_ORIGIN_VERIFICATION=false), which only serves "
            "requests arriving on the API process's own loopback interface; "
            "fix: call the API through the workshop storefront, or configure "
            "MOSAIC_REQUIRE_ORIGIN_VERIFICATION=true with "
            "MOSAIC_ORIGIN_VERIFY_SECRET for a reachable deployment.",
        )
    presented = request.headers.get(_ORIGIN_HEADER, "")
    expected = settings.origin_verify_secret or ""
    if not expected or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            401,
            "Mosaic requires the workshop origin secret on this route; fix: "
            "call the API through the workshop storefront URL rather than "
            "this host directly.",
        )


@dataclass
class _RateWindow:
    """A fixed one-minute request counter, process-local."""

    limit: int
    lock: threading.Lock = field(default_factory=threading.Lock)
    window_started_at: float = field(default_factory=time.monotonic)
    count: int = 0

    def allow(self) -> bool:
        now = time.monotonic()
        with self.lock:
            if now - self.window_started_at >= 60.0:
                self.window_started_at = now
                self.count = 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True


class _AdmissionState:
    """Process-local active-run and rate-limit counters.

    Reconstructed whenever the configured limit changes, which only happens in
    tests: a running process reads `get_settings()` once per lifetime.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphore: threading.BoundedSemaphore | None = None
        self._configured_concurrency: int | None = None
        self._window: _RateWindow | None = None
        self._configured_rate: int | None = None

    def semaphore_for(self, limit: int) -> threading.BoundedSemaphore:
        with self._lock:
            if self._semaphore is None or self._configured_concurrency != limit:
                self._semaphore = threading.BoundedSemaphore(limit)
                self._configured_concurrency = limit
            return self._semaphore

    def window_for(self, limit: int) -> _RateWindow:
        with self._lock:
            if self._window is None or self._configured_rate != limit:
                self._window = _RateWindow(limit=limit)
                self._configured_rate = limit
            return self._window

    def reset(self) -> None:
        with self._lock:
            self._semaphore = None
            self._configured_concurrency = None
            self._window = None
            self._configured_rate = None


_admission = _AdmissionState()


def reset_admission_state() -> None:
    """Test-only: clear process-local admission counters between test cases."""
    _admission.reset()


def _admission_rejected(detail: str) -> HTTPException:
    return HTTPException(429, detail, headers={"Retry-After": "5"})


def _acquire() -> threading.BoundedSemaphore:
    """Check the rate budget, then reserve one active-run slot.

    Raises:
        HTTPException: 429 with retry guidance, before any database or model
            call, when the shared rate or concurrency budget is exhausted.
    """
    settings = get_settings()
    window = _admission.window_for(settings.model_rate_limit_per_minute)
    if not window.allow():
        raise _admission_rejected(
            "Mosaic is at its request-rate limit for search and agent routes "
            f"({settings.model_rate_limit_per_minute} per minute for this "
            "process); fix: retry in a few seconds."
        )
    semaphore = _admission.semaphore_for(settings.max_concurrent_model_runs)
    if not semaphore.acquire(blocking=False):
        raise _admission_rejected(
            "Mosaic is at its concurrent-run limit for search and agent routes "
            f"({settings.max_concurrent_model_runs} active in this process); "
            "fix: retry in a few seconds."
        )
    return semaphore


def require_model_admission() -> Iterator[None]:
    """FastAPI dependency: admit one model-backed or expensive-diagnostic call.

    A generator dependency, so FastAPI releases the slot in its `finally` after
    the route returns, raises, or is cancelled -- including a timeout or a
    client disconnect during a synchronous route's threadpool execution.
    """
    semaphore = _acquire()
    try:
        yield
    finally:
        semaphore.release()


def acquire_model_admission_slot() -> threading.BoundedSemaphore:
    """Admission for a caller that must hold the slot across an async
    generator body (the streaming agent route) rather than a dependency's own
    teardown. Pair with `release_model_admission_slot` in every exit path.
    """
    return _acquire()


def release_model_admission_slot(semaphore: threading.BoundedSemaphore) -> None:
    semaphore.release()
