#!/usr/bin/env python3
"""G-33 - corpus diversity and signal coverage.

Read-only. The gate measures the current derived corpus, rather than a fixture
or generated sample, so a regression in the live evidence builder cannot hide
behind an updated expectation. A document body is reconstructed from its current
chunks because retrieval.documents intentionally stores indexed metadata only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-33"
TITLE = "corpus diversity and signal coverage"

# These expectations are deliberately independent of the corpus being judged.
# Deriving either list from the current rows would let a missing category turn
# a broken capture into a vacuous pass.
SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")
PHASES = ("backfill", "pool_exhaustion", "recovery", "plan_regression")
SIMILARITY_THRESHOLD = 0.6
MAX_NEAR_DUPLICATE_RATE = 0.15

CORPUS_SQL = """
WITH docs AS (
  SELECT
    document.document_version_id,
    coalesce(
      string_agg(chunk.chunk_text, E'\n' ORDER BY chunk.chunk_ordinal),
      ''
    ) AS body,
    document.metadata ->> 'telemetry_type' AS signal_type,
    document.metadata ->> 'phase' AS phase
  FROM retrieval.documents AS document
  JOIN retrieval.chunks AS chunk
    ON chunk.document_version_id = document.document_version_id
   AND chunk.is_current
  WHERE document.is_current
  GROUP BY document.document_version_id, document.metadata
),
pairs AS (
  SELECT
    count(*) AS total_pairs,
    count(*) FILTER (
      WHERE similarity(left_document.body, right_document.body)
        > %(threshold)s
    ) AS near_duplicate_pairs
  FROM docs AS left_document
  JOIN docs AS right_document
    ON left_document.document_version_id < right_document.document_version_id
)
SELECT
  (SELECT count(*) FROM docs) AS document_count,
  (SELECT total_pairs FROM pairs) AS total_pairs,
  (SELECT near_duplicate_pairs FROM pairs) AS near_duplicate_pairs,
  (
    SELECT coalesce(
      array_agg(DISTINCT signal_type ORDER BY signal_type)
        FILTER (WHERE signal_type IS NOT NULL),
      ARRAY[]::text[]
    )
    FROM docs
  ) AS signal_types,
  (
    SELECT coalesce(
      array_agg(DISTINCT phase ORDER BY phase)
        FILTER (WHERE phase IS NOT NULL),
      ARRAY[]::text[]
    )
    FROM docs
  ) AS phases
"""


@dataclass(frozen=True)
class CorpusMeasurement:
    document_count: int
    total_pairs: int
    near_duplicate_pairs: int
    signal_types: frozenset[str]
    phases: frozenset[str]

    @property
    def near_duplicate_rate(self) -> float:
        if self.total_pairs == 0:
            return 0.0
        return self.near_duplicate_pairs / self.total_pairs


def measure(connection) -> CorpusMeasurement:
    """Read one aggregate measurement from the current derived corpus."""
    row = connection.execute(
        CORPUS_SQL,
        {"threshold": SIMILARITY_THRESHOLD},
    ).fetchone()
    return CorpusMeasurement(
        document_count=row["document_count"],
        total_pairs=row["total_pairs"],
        near_duplicate_pairs=row["near_duplicate_pairs"],
        signal_types=frozenset(row["signal_types"] or ()),
        phases=frozenset(row["phases"] or ()),
    )


def validate_measurement(measurement: CorpusMeasurement) -> None:
    """Fail with every missing coverage category and the measured duplicate rate."""
    missing_signal_types = sorted(set(SIGNAL_TYPES) - measurement.signal_types)
    missing_phases = sorted(set(PHASES) - measurement.phases)
    failures: list[str] = []
    if missing_signal_types:
        failures.append(f"missing signal types: {missing_signal_types}")
    if missing_phases:
        failures.append(f"missing phases: {missing_phases}")
    if measurement.near_duplicate_rate >= MAX_NEAR_DUPLICATE_RATE:
        failures.append(
            "near-duplicate rate "
            f"{measurement.near_duplicate_rate:.2%} "
            f"({measurement.near_duplicate_pairs}/{measurement.total_pairs} pairs) "
            f"must be below {MAX_NEAR_DUPLICATE_RATE:.2%}"
        )
    require(not failures, "; ".join(failures))


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not configured")
    print(f"  database: {redact_dsn(dsn)}")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    try:
        with psycopg.connect(
            dsn,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as connection:
            corpus = measure(connection)
    except psycopg.errors.UndefinedTable:
        return finish(GATE_ID, BLOCKED, "retrieval corpus schema is not applied")
    except psycopg.errors.UndefinedColumn:
        return finish(GATE_ID, BLOCKED, "retrieval corpus schema is not applied")
    except psycopg.OperationalError as error:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {error}")

    if corpus.document_count == 0:
        return finish(
            GATE_ID,
            BLOCKED,
            "current retrieval corpus is empty; admit and index a live capture first",
        )

    validate_measurement(corpus)
    return finish(
        GATE_ID,
        PASS,
        (
            f"{corpus.document_count} current documents; "
            f"signal types={sorted(corpus.signal_types)}; "
            f"phases={sorted(corpus.phases)}; "
            f"near-duplicate rate={corpus.near_duplicate_rate:.2%} "
            f"({corpus.near_duplicate_pairs}/{corpus.total_pairs} pairs, "
            f"threshold < {MAX_NEAR_DUPLICATE_RATE:.0%})"
        ),
    )


if __name__ == "__main__":
    main_guard(run)
