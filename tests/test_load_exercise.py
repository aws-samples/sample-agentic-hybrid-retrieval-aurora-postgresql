"""Bounded concurrency exercise: request mix, abort conditions, report arithmetic.

Uses `httpx.MockTransport` rather than a real socket, per the task's "fake
HTTP server or mocked client" instruction: `httpx.Client(transport=...)` is
the same client class the script uses in production, so these tests exercise
the real request-building and response-parsing code, only the network layer
is a stand-in.
"""

from __future__ import annotations

import random
import threading
import time
from collections import Counter

import httpx
import pytest

from scripts.load_exercise import (
    LoadExerciseConfig,
    LoadExerciseError,
    Sample,
    admission_context,
    build_report,
    check_abort,
    choose_kind,
    discover_admission_limits,
    run_exercise,
)


def _config(**overrides) -> LoadExerciseConfig:
    defaults = {"api_url": "http://workshop-host", "condition": "warm"}
    defaults.update(overrides)
    return LoadExerciseConfig(**defaults)


# --------------------------------------------------------------------------
# Configuration validation
# --------------------------------------------------------------------------


def test_config_rejects_an_unknown_condition():
    with pytest.raises(LoadExerciseError):
        _config(condition="lukewarm")


def test_config_rejects_all_zero_weights():
    with pytest.raises(LoadExerciseError):
        _config(mix_weights={"search": 0, "fusion": 0, "agent": 0})


def test_config_rejects_a_non_positive_duration():
    with pytest.raises(LoadExerciseError):
        _config(duration_seconds=0)


def test_config_rejects_zero_concurrency():
    with pytest.raises(LoadExerciseError):
        _config(concurrency=0)


# --------------------------------------------------------------------------
# Request mix
# --------------------------------------------------------------------------


def test_choose_kind_respects_weights_over_many_draws():
    rng = random.Random(42)
    weights = {"search": 0.5, "fusion": 0.2, "agent": 0.3}
    counts = Counter(
        choose_kind(rng, weights, agent_available=True) for _ in range(20_000)
    )
    total = sum(counts.values())
    for kind, weight in weights.items():
        assert abs(counts[kind] / total - weight) < 0.02


def test_choose_kind_excludes_agent_once_capped():
    rng = random.Random(1)
    weights = {"search": 0.5, "fusion": 0.2, "agent": 0.3}
    draws = {choose_kind(rng, weights, agent_available=False) for _ in range(500)}
    assert draws == {"search", "fusion"}


def test_choose_kind_falls_back_when_only_agent_has_weight_and_is_capped():
    rng = random.Random(1)
    with pytest.raises(LoadExerciseError):
        choose_kind(rng, {"search": 0, "fusion": 0, "agent": 1}, agent_available=False)


# --------------------------------------------------------------------------
# Abort conditions
# --------------------------------------------------------------------------


def _samples(*, count, status_code, latency_ms=10.0, kind="search"):
    return [
        Sample(
            kind=kind,
            status_code=status_code,
            latency_ms=latency_ms,
            error=None,
            timestamp=0.0,
        )
        for _ in range(count)
    ]


def test_check_abort_stays_quiet_below_min_samples():
    config = _config(min_samples_before_abort=10, error_rate_ceiling=0.1)
    samples = _samples(count=5, status_code=503)
    assert check_abort(samples, config) is None


def test_check_abort_trips_on_error_rate():
    config = _config(min_samples_before_abort=5, error_rate_ceiling=0.5)
    samples = _samples(count=3, status_code=200) + _samples(count=3, status_code=503)
    assert check_abort(samples, config) == "error_rate_ceiling"


def test_check_abort_does_not_trip_below_the_error_rate_ceiling():
    config = _config(min_samples_before_abort=5, error_rate_ceiling=0.9)
    samples = _samples(count=8, status_code=200) + _samples(count=2, status_code=503)
    assert check_abort(samples, config) is None


def test_check_abort_trips_on_latency_ceiling():
    config = _config(
        min_samples_before_abort=5,
        error_rate_ceiling=0.99,
        latency_ceiling_ms=100.0,
        latency_window_size=5,
    )
    samples = _samples(count=5, status_code=200, latency_ms=500.0)
    assert check_abort(samples, config) == "latency_ceiling"


def test_check_abort_latency_window_ignores_stale_high_latency_samples():
    config = _config(
        min_samples_before_abort=5,
        error_rate_ceiling=0.99,
        latency_ceiling_ms=100.0,
        latency_window_size=3,
    )
    stale_slow = _samples(count=5, status_code=200, latency_ms=9_000.0)
    recent_fast = _samples(count=3, status_code=200, latency_ms=10.0)
    assert check_abort(stale_slow + recent_fast, config) is None


def test_exceptions_count_as_errors_for_the_abort_gate():
    config = _config(min_samples_before_abort=4, error_rate_ceiling=0.5)
    samples = [
        Sample(
            kind="search",
            status_code=None,
            latency_ms=1.0,
            error="ConnectError",
            timestamp=0.0,
        )
        for _ in range(4)
    ]
    assert check_abort(samples, config) == "error_rate_ceiling"


# --------------------------------------------------------------------------
# Admission context
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["admission", "admission_control", "rate_limit", "rate_limiting"]
)
def test_discover_admission_limits_checks_every_known_key(key):
    readiness = {key: {"max_concurrent_requests": 16}}
    assert discover_admission_limits(readiness) == {"max_concurrent_requests": 16}


def test_discover_admission_limits_returns_none_when_absent():
    assert discover_admission_limits({"status": "ready"}) is None


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_admission_context_prefers_served_config():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"admission": {"max_concurrent_requests": 8}})

    config = _config(expected_max_concurrent_requests=100)
    with _mock_client(handler) as client:
        context = admission_context(client, config)
    assert context == {"source": "served", "limits": {"max_concurrent_requests": 8}}


def test_admission_context_falls_back_to_cli_flag_when_not_served():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ready"})

    config = _config(expected_max_concurrent_requests=12)
    with _mock_client(handler) as client:
        context = admission_context(client, config)
    assert context == {"source": "cli_flag", "limits": {"max_concurrent_requests": 12}}


def test_admission_context_is_unknown_when_readiness_is_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    config = _config()
    with _mock_client(handler) as client:
        context = admission_context(client, config)
    assert context == {"source": "unknown", "limits": None}


# --------------------------------------------------------------------------
# Report arithmetic
# --------------------------------------------------------------------------


def test_build_report_computes_percentiles_error_rate_and_saturation_counts():
    samples = [
        Sample(
            kind="search", status_code=200, latency_ms=100.0, error=None, timestamp=0.0
        ),
        Sample(
            kind="search", status_code=200, latency_ms=200.0, error=None, timestamp=0.0
        ),
        Sample(
            kind="search",
            status_code=429,
            latency_ms=50.0,
            error="HTTP 429",
            timestamp=0.0,
        ),
        Sample(
            kind="agent",
            status_code=503,
            latency_ms=10.0,
            error="HTTP 503",
            timestamp=0.0,
        ),
    ]
    report = build_report(
        _config(),
        samples,
        abort_reason=None,
        recovery=None,
        admission={"source": "unknown", "limits": None},
        wall_clock_seconds=12.3,
        agent_calls_issued=1,
    )
    assert report["kind"] == "measured"
    assert report["sample_count"] == 4
    assert report["error_count"] == 2
    assert report["error_rate"] == 0.5
    assert report["saturation_signals"] == {"429": 1, "503": 1}
    assert report["per_kind"]["search"]["count"] == 3
    assert report["per_kind"]["search"]["error_count"] == 1
    assert report["per_kind"]["agent"]["count"] == 1
    assert report["per_kind"]["fusion"]["count"] == 0
    assert report["per_kind"]["fusion"]["latency"] is None
    assert report["agent_calls_issued"] == 1
    assert report["wall_clock_seconds"] == 12.3


def test_build_report_on_zero_samples_does_not_divide_by_zero():
    report = build_report(
        _config(),
        [],
        abort_reason=None,
        recovery=None,
        admission={"source": "unknown", "limits": None},
        wall_clock_seconds=1.0,
        agent_calls_issued=0,
    )
    assert report["sample_count"] == 0
    assert report["error_rate"] is None
    assert report["latency"] is None


# --------------------------------------------------------------------------
# End-to-end against a fake server
# --------------------------------------------------------------------------


def test_run_exercise_completes_on_duration_and_respects_the_agent_cap():
    call_counts = Counter()
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            call_counts[request.url.path] += 1
        return httpx.Response(200, json={"diagnostics": {}, "trace": [], "results": []})

    config = _config(
        duration_seconds=0.4,
        concurrency=3,
        check_interval_seconds=0.02,
        max_agent_calls=2,
        error_rate_ceiling=0.99,
        min_samples_before_abort=10_000,
        request_timeout_seconds=5.0,
    )
    with _mock_client(handler) as client:
        report = run_exercise(client, config)

    assert report["kind"] == "measured"
    assert report["abort_reason"] is None
    assert report["sample_count"] > 0
    assert report["agent_calls_issued"] <= 2
    assert call_counts["/api/agent/answer"] <= 2
    assert (
        report["per_kind"]["search"]["count"] + report["per_kind"]["fusion"]["count"]
        > 0
    )


def test_run_exercise_aborts_early_on_a_persistent_error_rate_and_reports_recovery():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "database is not ready"})

    config = _config(
        duration_seconds=30.0,  # would run far longer than the test if abort failed
        concurrency=2,
        check_interval_seconds=0.02,
        min_samples_before_abort=3,
        error_rate_ceiling=0.5,
        recovery_window_seconds=0.1,
        recovery_probe_interval_seconds=0.01,
        request_timeout_seconds=5.0,
    )
    with _mock_client(handler) as client:
        report = run_exercise(client, config)

    assert report["abort_reason"] == "error_rate_ceiling"
    assert report["wall_clock_seconds"] < 5.0
    assert report["error_rate"] == 1.0
    assert report["recovery"] is not None
    assert report["recovery"]["recovered"] is False


def test_run_exercise_reports_recovery_after_the_server_starts_answering_again():
    """A single slow worker so the abort check sees only the failing calls.

    With no per-call delay a single worker thread can blast through hundreds
    of requests before the monitor thread's next `check_interval_seconds`
    wake-up, drowning out a handful of early failures in a flood of later
    successes. A small fixed per-call delay, comparable to the check and
    probe intervals, keeps the load phase's sample count small and
    deterministic: exactly the first two calls, both failures, trip the
    abort before request 3 (which would already succeed) is ever issued.
    """
    call_counts = Counter()
    lock = threading.Lock()
    fail_until = 2

    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.05)
        with lock:
            call_counts["total"] += 1
            current = call_counts["total"]
        if current <= fail_until:
            return httpx.Response(503, json={"detail": "saturated"})
        return httpx.Response(200, json={"diagnostics": {}, "results": []})

    config = _config(
        duration_seconds=30.0,
        concurrency=1,
        check_interval_seconds=0.01,
        min_samples_before_abort=2,
        error_rate_ceiling=0.5,
        recovery_window_seconds=5.0,
        recovery_probe_interval_seconds=0.01,
        request_timeout_seconds=5.0,
        mix_weights={"search": 1.0, "fusion": 0.0, "agent": 0.0},
    )
    with _mock_client(handler) as client:
        report = run_exercise(client, config)

    assert report["abort_reason"] == "error_rate_ceiling"
    # A worker can race the monitor's next poll and issue one extra request
    # before `stop_event` is observed; bound rather than pin the count.
    assert fail_until <= report["sample_count"] <= fail_until + 3
    assert report["error_count"] >= fail_until
    assert report["recovery"]["recovered"] is True
    assert report["recovery"]["recovered_after_seconds"] is not None
