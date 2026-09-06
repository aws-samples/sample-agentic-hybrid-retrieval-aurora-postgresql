"""The reported total must cover everything the caller waited for.

`total_latency_ms` used to stop the clock before the receipt rows were written
and before coverage was assessed, so work the participant waited through was
invisible in the number the receipt showed them. Diagnostics are the workshop's
deliverable, so this is measured rather than asserted in prose: the clock is
advanced inside each stage and the total has to move with it.
"""

from __future__ import annotations

from typing import Any, Self

import pytest

from service import retrieval as retrieval_module
from service.models import SearchRequest
from service.retrieval import RetrievalService

COVERAGE_DELAY_SECONDS = 5.0
PERSISTENCE_DELAY_SECONDS = 2.0


class _Clock:
    """A perf counter that only moves when a stage says it did."""

    def __init__(self) -> None:
        self.now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Cursor:
    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.rows_written = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def executemany(self, _sql: str, rows: Any) -> None:
        # Writing the receipt costs real time against a workshop cluster.
        self.rows_written += len(list(rows))
        self._clock.advance(PERSISTENCE_DELAY_SECONDS)


class _Result:
    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        # No candidate survives the gates, which is the cheapest way through the
        # whole method: the timing boundary is the subject, not the ranking.
        return []


class _Connection:
    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.statements: list[str] = []
        self.cursors: list[_Cursor] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        created = _Cursor(self._clock)
        self.cursors.append(created)
        return created

    def execute(self, sql: str, _parameters: Any = None) -> _Result:
        self.statements.append(sql)
        return _Result()

    def commit(self) -> None:
        return None


class _Embedder:
    model_id = "us.cohere.embed-v4:0"

    def embed_query(self, _query: str) -> list[float]:
        return [0.0] * 1024


@pytest.fixture()
def measured(monkeypatch):
    """One search whose coverage and receipt write both cost measurable time."""
    clock = _Clock()
    connection = _Connection(clock)
    monkeypatch.setattr(retrieval_module, "time", clock)

    captured: dict[str, Any] = {}

    def coverage(_query: str, **_kwargs: Any):
        clock.advance(COVERAGE_DELAY_SECONDS)
        return captured["verdict"]

    from service.coverage import summarize

    captured["verdict"] = summarize([])
    monkeypatch.setattr(retrieval_module, "assess_coverage", coverage)

    service = RetrievalService(
        embedding_provider=_Embedder(),
        connection_factory=lambda: connection,
    )
    response = service.search(SearchRequest(query="quiet office keyboard"))
    return response, connection


def test_the_total_covers_the_coverage_assessment(measured):
    """The audit's counterexample: five seconds inside coverage moved nothing."""
    response, _connection = measured
    timings = response.diagnostics.stage_timings_ms

    assert timings["coverage"] == pytest.approx(COVERAGE_DELAY_SECONDS * 1000)
    assert response.diagnostics.total_latency_ms >= COVERAGE_DELAY_SECONDS * 1000


def test_the_total_covers_writing_the_receipt(measured):
    """The result rows are written before the caller is answered, so they count."""
    response, _connection = measured
    timings = response.diagnostics.stage_timings_ms

    assert timings["result_persistence"] == pytest.approx(
        PERSISTENCE_DELAY_SECONDS * 1000
    )
    assert (
        response.diagnostics.total_latency_ms
        >= (COVERAGE_DELAY_SECONDS + PERSISTENCE_DELAY_SECONDS) * 1000
    )


def test_the_persisted_total_is_the_one_the_response_reports(measured):
    """One number, not two.

    The receipt in Aurora and the diagnostics on screen have to agree, or a
    participant comparing them is reading two different measurements of the
    same search.
    """
    response, connection = measured

    assert any("UPDATE mosaic.search_event" in sql for sql in connection.statements)
    assert response.diagnostics.total_latency_ms == pytest.approx(
        (COVERAGE_DELAY_SECONDS + PERSISTENCE_DELAY_SECONDS) * 1000,
        abs=1,
    )
