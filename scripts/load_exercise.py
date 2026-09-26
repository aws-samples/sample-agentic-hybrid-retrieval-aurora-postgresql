"""Bounded concurrency exercise against the served Mosaic HTTP API.

`READINESS.md`'s clean-account acceptance test asks for rehearsed reranker and
Ask Mosaic calls, but names no participant-concurrency check: nothing in this
repository ever sent Mosaic more than one request at a time and measured what
happened. This script is that check. It drives a bounded mix of
`POST /api/search`, `POST /api/retrieval/fusion-comparison`, and
`POST /api/agent/answer` against a real, already-deployed API for a fixed
wall-clock duration and a fixed worker count, and reports what came back:
sample counts, errors, p50/p95/p99 latency, and 429/503 counts, per request
kind and overall.

It is opt-in and bounded on purpose:

- `--duration-seconds` and `--concurrency` set a hard ceiling on how long and
  how wide the exercise runs;
- `--max-agent-calls` caps the number of `/api/agent/answer` calls the whole
  run may issue, because each one can drive up to
  `service.agent.build_agent`'s server-side `max_tool_calls` (10 by default)
  worth of retrieval and a Bedrock synthesis call, the most expensive request
  this API serves;
- `--rerank/--no-rerank` toggles the Cohere rerank call on search requests
  (fusion comparison never reranks; see `docs/api-contract.md`);
- `--error-rate-ceiling`, `--latency-ceiling-ms`, and `--duration-seconds` are
  abort conditions: the load loop stops itself the moment any one trips,
  rather than needing an operator watching a terminal to Ctrl-C it.

A separate agent on another branch is adding admission control and rate
limits to the API. This script does not assume that work has landed: at
startup it reads `GET /api/readiness` and looks for a served admission/rate
limit block under a handful of plausible keys (`admission`,
`admission_control`, `rate_limit`, `rate_limiting`). When present, it is
echoed into the report under `admission_context` with `source: "served"` so a
reviewer can compare what the server claims against what this run measured.
When absent, `--expected-max-concurrent-requests` supplies the same slot from
the command line with `source: "cli_flag"`, and `source: "unknown"` when
neither is available. Nothing here changes its own concurrency based on the
discovered value -- the whole point of the exercise is to probe the server's
admission behavior, which sometimes means running well above its declared
ceiling on purpose.

"Cold" and "warm" are operator-declared, not inferred. There is no reliable,
server-observable signal in this codebase for "this is the first request
since deployment" (Bedrock cold starts, Aurora connection warm-up, and OS
page-cache state are all invisible to an HTTP client), so guessing would
violate the workshop's own rule to never invent measured behavior. Run this
script once with `--condition cold` immediately after a fresh deployment's
first request and again with `--condition warm` after the system has served
traffic for a while; each run's report is self-labeled, and comparing the two
files is how a reviewer sees cold-versus-warm behavior.

Simulated projections belong in `scripts/simulate_scale.py`, whose CSV rows
carry `projection_kind: "simulated_calibrated"`. Every report this script
writes carries `"kind": "measured"` instead, the same discriminator
`data/benchmarks/hnsw_measured.json` and `scripts/rehearsal.py` use, so the
two can never be confused by a downstream reader that only checks one field.

Usage:

    uv run python scripts/load_exercise.py --api-url http://127.0.0.1:8000 \\
        --condition warm --duration-seconds 120 --concurrency 8 \\
        --output build/load-exercise-warm.json

Tests exercise every pure function (`choose_kind`, `check_abort`, `_summary`,
`build_report`) directly and drive one short end-to-end run through
`httpx.MockTransport`, per `tests/test_load_exercise.py`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MANIFEST_KIND = "measured"  # see scripts/rehearsal.py for the discriminator's origin

REQUEST_KINDS = ("search", "fusion", "agent")
CONDITIONS = ("cold", "warm")
SATURATION_STATUS_CODES = (429, 503)

DEFAULT_SEARCH_QUESTION = "wireless noise-cancelling headphones under $200"
DEFAULT_AGENT_QUESTION = (
    "Compare quiet mechanical keyboards for shared-office calls under $200"
)

_ADMISSION_KEYS = ("admission", "admission_control", "rate_limit", "rate_limiting")


class LoadExerciseError(RuntimeError):
    """A configuration or transport problem that stops the exercise before it starts."""


# --------------------------------------------------------------------------
# Configuration and per-request records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadExerciseConfig:
    api_url: str
    condition: str
    duration_seconds: float = 60.0
    concurrency: int = 4
    mix_weights: dict[str, float] = field(
        default_factory=lambda: {"search": 0.5, "fusion": 0.2, "agent": 0.3}
    )
    rerank: bool = True
    max_agent_calls: int = 20
    error_rate_ceiling: float = 0.5
    latency_ceiling_ms: float = 5_000.0
    min_samples_before_abort: int = 10
    latency_window_size: int = 20
    check_interval_seconds: float = 1.0
    request_timeout_seconds: float = 30.0
    recovery_window_seconds: float = 30.0
    recovery_probe_interval_seconds: float = 2.0
    search_question: str = DEFAULT_SEARCH_QUESTION
    agent_question: str = DEFAULT_AGENT_QUESTION
    seed: int = 0
    expected_max_concurrent_requests: int | None = None

    def __post_init__(self) -> None:
        if self.condition not in CONDITIONS:
            raise LoadExerciseError(
                f"found condition {self.condition!r}; fix: use one of {CONDITIONS}"
            )
        if self.duration_seconds <= 0:
            raise LoadExerciseError(
                "found duration_seconds <= 0; fix: pass a positive value"
            )
        if self.concurrency < 1:
            raise LoadExerciseError("found concurrency < 1; fix: pass at least 1")
        if any(weight < 0 for weight in self.mix_weights.values()):
            raise LoadExerciseError(
                "found a negative mix weight; fix: use non-negative weights"
            )
        if sum(self.mix_weights.values()) <= 0:
            raise LoadExerciseError(
                "found all mix weights at zero; fix: give at least one request kind a positive weight"
            )
        if not 0 < self.error_rate_ceiling <= 1:
            raise LoadExerciseError(
                "found error_rate_ceiling outside (0, 1]; fix: pass a fraction"
            )
        if self.max_agent_calls < 0:
            raise LoadExerciseError("found max_agent_calls < 0; fix: pass 0 or more")


@dataclass
class Sample:
    kind: str
    status_code: int | None
    latency_ms: float
    error: str | None
    timestamp: float

    @property
    def is_error(self) -> bool:
        return self.error is not None or (self.status_code or 0) >= 400


@dataclass
class RunState:
    started_monotonic: float
    samples: list[Sample] = field(default_factory=list)
    agent_calls_issued: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


# --------------------------------------------------------------------------
# Pure helpers: request mix, abort conditions, percentile arithmetic
# --------------------------------------------------------------------------


def choose_kind(
    rng: random.Random, weights: dict[str, float], *, agent_available: bool
) -> str:
    """Pick one request kind by weight, excluding "agent" once its cap is hit."""
    candidates = {
        kind: weight
        for kind, weight in weights.items()
        if weight > 0 and (kind != "agent" or agent_available)
    }
    if not candidates:
        candidates = {
            kind: weight
            for kind, weight in weights.items()
            if weight > 0 and kind != "agent"
        }
    if not candidates:
        raise LoadExerciseError(
            "found no request kind available (agent capped and no other weight positive); "
            "fix: give search or fusion a positive weight"
        )
    total = sum(candidates.values())
    draw = rng.uniform(0, total)
    cumulative = 0.0
    for kind, weight in candidates.items():
        cumulative += weight
        if draw <= cumulative:
            return kind
    return next(iter(candidates))


def check_abort(samples: list[Sample], config: LoadExerciseConfig) -> str | None:
    """Return the tripped abort condition's name, or None if the run may continue."""
    if len(samples) < config.min_samples_before_abort:
        return None
    error_count = sum(1 for sample in samples if sample.is_error)
    if error_count / len(samples) >= config.error_rate_ceiling:
        return "error_rate_ceiling"
    window = samples[-config.latency_window_size :]
    if len(window) >= config.min_samples_before_abort:
        p95 = _percentile(sorted(sample.latency_ms for sample in window), 0.95)
        if p95 >= config.latency_ceiling_ms:
            return "latency_ceiling"
    return None


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(latencies: list[float]) -> dict[str, float] | None:
    if not latencies:
        return None
    ordered = sorted(latencies)
    return {
        "min_ms": round(ordered[0], 1),
        "p50_ms": round(_percentile(ordered, 0.50), 1),
        "p95_ms": round(_percentile(ordered, 0.95), 1),
        "p99_ms": round(_percentile(ordered, 0.99), 1),
        "max_ms": round(ordered[-1], 1),
    }


# --------------------------------------------------------------------------
# Request builders
# --------------------------------------------------------------------------


def _search_payload(question: str, *, rerank: bool) -> dict[str, Any]:
    return {
        "query": question,
        "filters": {},
        "limit": 10,
        "include_diagnostics": True,
        "rerank": rerank,
    }


def _agent_payload(question: str) -> dict[str, Any]:
    return {"question": question, "filters": {}, "result_limit": 6}


def _issue_request(client: Any, config: LoadExerciseConfig, kind: str) -> Sample:
    import httpx

    if kind == "search":
        path, payload = (
            "/api/search",
            _search_payload(config.search_question, rerank=config.rerank),
        )
    elif kind == "fusion":
        # Fusion comparison applies unweighted and weighted RRF only; it never
        # reranks (docs/api-contract.md), so rerank is fixed off regardless of
        # --rerank for clarity, not because the endpoint reads the field.
        path = "/api/retrieval/fusion-comparison"
        payload = _search_payload(config.search_question, rerank=False)
    elif kind == "agent":
        path, payload = "/api/agent/answer", _agent_payload(config.agent_question)
    else:
        raise LoadExerciseError(
            f"found request kind {kind!r}; fix: use one of {REQUEST_KINDS}"
        )
    url = config.api_url.rstrip("/") + path
    started = time.perf_counter()
    try:
        response = client.post(
            url, json=payload, timeout=config.request_timeout_seconds
        )
    except httpx.HTTPError as error:
        return Sample(
            kind=kind,
            status_code=None,
            latency_ms=(time.perf_counter() - started) * 1_000,
            error=type(error).__name__,
            timestamp=time.time(),
        )
    latency_ms = (time.perf_counter() - started) * 1_000
    error = None if response.status_code < 400 else f"HTTP {response.status_code}"
    return Sample(
        kind=kind,
        status_code=response.status_code,
        latency_ms=latency_ms,
        error=error,
        timestamp=time.time(),
    )


# --------------------------------------------------------------------------
# Admission context (served config if available, else the CLI's expectation)
# --------------------------------------------------------------------------


def discover_admission_limits(readiness: dict[str, Any]) -> dict[str, Any] | None:
    for key in _ADMISSION_KEYS:
        value = readiness.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def admission_context(client: Any, config: LoadExerciseConfig) -> dict[str, Any]:
    import httpx

    try:
        response = client.get(
            config.api_url.rstrip("/") + "/api/readiness",
            timeout=config.request_timeout_seconds,
        )
        response.raise_for_status()
        served = discover_admission_limits(response.json())
    except (httpx.HTTPError, ValueError):
        served = None
    if served is not None:
        return {"source": "served", "limits": served}
    if config.expected_max_concurrent_requests is not None:
        return {
            "source": "cli_flag",
            "limits": {
                "max_concurrent_requests": config.expected_max_concurrent_requests
            },
        }
    return {"source": "unknown", "limits": None}


# --------------------------------------------------------------------------
# The load loop and recovery probe
# --------------------------------------------------------------------------


def _worker(
    client: Any,
    config: LoadExerciseConfig,
    state: RunState,
    stop_event: threading.Event,
    rng: random.Random,
) -> None:
    while not stop_event.is_set():
        with state.lock:
            agent_available = state.agent_calls_issued < config.max_agent_calls
        kind = choose_kind(rng, config.mix_weights, agent_available=agent_available)
        if kind == "agent":
            with state.lock:
                if state.agent_calls_issued >= config.max_agent_calls:
                    continue
                state.agent_calls_issued += 1
        sample = _issue_request(client, config, kind)
        with state.lock:
            state.samples.append(sample)


def _probe_recovery(client: Any, config: LoadExerciseConfig) -> dict[str, Any]:
    """Probe with plain search requests, one at a time, until recovery or timeout."""
    deadline = time.monotonic() + config.recovery_window_seconds
    started = time.monotonic()
    probes: list[Sample] = []
    recovered_after_seconds: float | None = None
    while time.monotonic() < deadline:
        sample = _issue_request(client, config, "search")
        probes.append(sample)
        if not sample.is_error:
            recovered_after_seconds = round(time.monotonic() - started, 2)
            break
        time.sleep(config.recovery_probe_interval_seconds)
    return {
        "window_seconds": config.recovery_window_seconds,
        "probe_count": len(probes),
        "recovered": recovered_after_seconds is not None,
        "recovered_after_seconds": recovered_after_seconds,
    }


def build_report(
    config: LoadExerciseConfig,
    samples: list[Sample],
    *,
    abort_reason: str | None,
    recovery: dict[str, Any] | None,
    admission: dict[str, Any] | None,
    wall_clock_seconds: float,
    agent_calls_issued: int,
) -> dict[str, Any]:
    total = len(samples)
    error_count = sum(1 for sample in samples if sample.is_error)
    status_counts = Counter(
        sample.status_code for sample in samples if sample.status_code is not None
    )
    per_kind = {
        kind: {
            "count": sum(1 for sample in samples if sample.kind == kind),
            "error_count": sum(
                1 for sample in samples if sample.kind == kind and sample.is_error
            ),
            "latency": _summary(
                [sample.latency_ms for sample in samples if sample.kind == kind]
            ),
        }
        for kind in REQUEST_KINDS
    }
    return {
        "kind": MANIFEST_KIND,
        "condition": config.condition,
        "api_url": config.api_url,
        "config": {
            "duration_seconds": config.duration_seconds,
            "concurrency": config.concurrency,
            "mix_weights": config.mix_weights,
            "rerank": config.rerank,
            "max_agent_calls": config.max_agent_calls,
            "error_rate_ceiling": config.error_rate_ceiling,
            "latency_ceiling_ms": config.latency_ceiling_ms,
        },
        "admission_context": admission,
        "wall_clock_seconds": round(wall_clock_seconds, 2),
        "sample_count": total,
        "error_count": error_count,
        "error_rate": round(error_count / total, 4) if total else None,
        "agent_calls_issued": agent_calls_issued,
        "latency": _summary([sample.latency_ms for sample in samples]),
        "per_kind": per_kind,
        "saturation_signals": {
            str(code): status_counts.get(code, 0) for code in SATURATION_STATUS_CODES
        },
        "abort_reason": abort_reason,
        "recovery": recovery,
    }


def run_exercise(client: Any, config: LoadExerciseConfig) -> dict[str, Any]:
    """Drive the bounded mix for `config.duration_seconds` or until an abort trips."""
    state = RunState(started_monotonic=time.monotonic())
    stop_event = threading.Event()
    threads = [
        threading.Thread(
            target=_worker,
            args=(
                client,
                config,
                state,
                stop_event,
                random.Random(config.seed + index),
            ),
            daemon=True,
        )
        for index in range(config.concurrency)
    ]
    for thread in threads:
        thread.start()

    abort_reason: str | None = None
    while True:
        if time.monotonic() - state.started_monotonic >= config.duration_seconds:
            break
        with state.lock:
            snapshot = list(state.samples)
        abort_reason = check_abort(snapshot, config)
        if abort_reason:
            break
        time.sleep(config.check_interval_seconds)
    stop_event.set()
    for thread in threads:
        thread.join(timeout=config.request_timeout_seconds + 5)

    with state.lock:
        final_samples = list(state.samples)
        agent_calls_issued = state.agent_calls_issued
    wall_clock_seconds = time.monotonic() - state.started_monotonic

    recovery = None
    if abort_reason and config.recovery_window_seconds > 0:
        recovery = _probe_recovery(client, config)

    admission = admission_context(client, config)
    return build_report(
        config,
        final_samples,
        abort_reason=abort_reason,
        recovery=recovery,
        admission=admission,
        wall_clock_seconds=wall_clock_seconds,
        agent_calls_issued=agent_calls_issued,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--condition", required=True, choices=CONDITIONS)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--search-weight", type=float, default=0.5)
    parser.add_argument("--fusion-weight", type=float, default=0.2)
    parser.add_argument("--agent-weight", type=float, default=0.3)
    parser.add_argument("--rerank", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-agent-calls", type=int, default=20)
    parser.add_argument("--error-rate-ceiling", type=float, default=0.5)
    parser.add_argument("--latency-ceiling-ms", type=float, default=5_000.0)
    parser.add_argument("--min-samples-before-abort", type=int, default=10)
    parser.add_argument("--latency-window-size", type=int, default=20)
    parser.add_argument("--check-interval-seconds", type=float, default=1.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--recovery-window-seconds", type=float, default=30.0)
    parser.add_argument("--recovery-probe-interval-seconds", type=float, default=2.0)
    parser.add_argument("--search-question", default=DEFAULT_SEARCH_QUESTION)
    parser.add_argument("--agent-question", default=DEFAULT_AGENT_QUESTION)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--expected-max-concurrent-requests", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = LoadExerciseConfig(
            api_url=args.api_url,
            condition=args.condition,
            duration_seconds=args.duration_seconds,
            concurrency=args.concurrency,
            mix_weights={
                "search": args.search_weight,
                "fusion": args.fusion_weight,
                "agent": args.agent_weight,
            },
            rerank=args.rerank,
            max_agent_calls=args.max_agent_calls,
            error_rate_ceiling=args.error_rate_ceiling,
            latency_ceiling_ms=args.latency_ceiling_ms,
            min_samples_before_abort=args.min_samples_before_abort,
            latency_window_size=args.latency_window_size,
            check_interval_seconds=args.check_interval_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            recovery_window_seconds=args.recovery_window_seconds,
            recovery_probe_interval_seconds=args.recovery_probe_interval_seconds,
            search_question=args.search_question,
            agent_question=args.agent_question,
            seed=args.seed,
            expected_max_concurrent_requests=args.expected_max_concurrent_requests,
        )
    except LoadExerciseError as error:
        print(f"load_exercise.py: {error}", file=sys.stderr)
        return 2

    import httpx

    with httpx.Client() as client:
        report = run_exercise(client, config)

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
