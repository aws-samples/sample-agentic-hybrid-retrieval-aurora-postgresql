#!/usr/bin/env python3
"""G-32 - additive evidence validation.

Read-only. Confirms one incident carries both captures, every record from each
capture has a current ready search document, and Validation Evidence adds
measured validation evidence without replacing Investigation Evidence.
"""
from __future__ import annotations

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

GATE_ID = "G-32"
TITLE = "additive evidence validation"

EXPECTED_PHASES = ("backfill", "pool_exhaustion", "recovery", "plan_regression")
EXPECTED_SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")
EXPECTED_WAVE_B_SIGNALS = ("meta", "plan")


def _distinct_values(connection, incident_evidence_id, field: str) -> set[str]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT structured ->> '{field}'
        FROM evidence.telemetry_evidence
        WHERE incident_evidence_id = %s
          AND structured ->> '{field}' IS NOT NULL
        """,
        (incident_evidence_id,),
    ).fetchall()
    return {row[0] for row in rows}


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set")
    print(f"  database: {redact_dsn(dsn)}")

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    try:
        with psycopg.connect(
            dsn,
            options="-c default_transaction_read_only=on",
        ) as connection:
            incident = connection.execute(
                """
                SELECT incident_evidence_id
                FROM evidence.incident_capture_runs
                WHERE capture_origin = 'participant_induced'
                GROUP BY incident_evidence_id
                HAVING bool_or(wave = 'A') AND bool_or(wave = 'B')
                ORDER BY max(capture_ended_at) DESC
                LIMIT 1
                """
            ).fetchone()
            if incident is None:
                waves = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT DISTINCT wave
                        FROM evidence.incident_capture_runs
                        ORDER BY wave
                        """
                    ).fetchall()
                ]
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"needs both evidence captures; found internal stages {waves}",
                )

            incident_evidence_id = incident[0]
            bundle_rows = connection.execute(
                """
                SELECT wave, count(*), min(source_bundle_uri)
                FROM evidence.incident_capture_runs
                WHERE incident_evidence_id = %s
                GROUP BY wave
                ORDER BY wave
                """,
                (incident_evidence_id,),
            ).fetchall()
            require(
                [(row[0], row[1]) for row in bundle_rows] == [("A", 1), ("B", 1)],
                "the selected incident must have exactly one capture per stage",
            )
            bundles = {row[0]: row[2] for row in bundle_rows}
            require(
                bundles["A"] != bundles["B"],
                "Investigation Evidence and Validation Evidence reused one "
                "source bundle URI",
            )

            coverage = {
                row[0]: (row[1], row[2])
                for row in connection.execute(
                    """
                    SELECT
                      capture.wave,
                      count(DISTINCT item.evidence_id) AS evidence_items,
                      count(DISTINCT document.evidence_id)
                        FILTER (
                          WHERE document.is_current
                            AND document.index_state = 'ready'
                        ) AS current_documents
                    FROM evidence.incident_capture_runs capture
                    JOIN evidence.evidence_items item
                      ON item.source_uri LIKE capture.source_bundle_uri || '/%%'
                     AND NOT item.is_deleted
                    LEFT JOIN retrieval.documents document
                      ON document.evidence_id = item.evidence_id
                    WHERE capture.incident_evidence_id = %s
                    GROUP BY capture.wave
                    ORDER BY capture.wave
                    """,
                    (incident_evidence_id,),
                ).fetchall()
            }
            for wave in ("A", "B"):
                require(
                    wave in coverage,
                    f"capture stage {wave} contributed no evidence",
                )
                evidence_items, current_documents = coverage[wave]
                require(
                    evidence_items == current_documents,
                    f"capture stage {wave} has {evidence_items} evidence items but "
                    f"{current_documents} current ready documents",
                )

            validates = connection.execute(
                """
                SELECT count(*)
                FROM evidence.incident_changes relation
                JOIN evidence.evidence_items change_item
                  ON change_item.evidence_id = relation.change_evidence_id
                WHERE relation.incident_evidence_id = %s
                  AND relation.relationship = 'validates'
                  AND change_item.source_uri LIKE %s || '/%%'
                """,
                (incident_evidence_id, bundles["B"]),
            ).fetchone()[0]
            require(
                validates >= 1,
                "Validation Evidence contributed no validates relationship",
            )

            phases = _distinct_values(connection, incident_evidence_id, "phase")
            missing_phases = sorted(set(EXPECTED_PHASES) - phases)
            require(
                not missing_phases,
                f"missing evidence phases: {missing_phases}",
            )

            signal_types = _distinct_values(
                connection, incident_evidence_id, "telemetry_type"
            )
            missing_signals = sorted(set(EXPECTED_SIGNAL_TYPES) - signal_types)
            require(
                not missing_signals,
                f"missing evidence signal types: {missing_signals}",
            )

            wave_b_signals = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT DISTINCT telemetry.structured ->> 'telemetry_type'
                    FROM evidence.telemetry_evidence telemetry
                    JOIN evidence.incident_capture_runs capture
                      ON capture.capture_id = telemetry.capture_id
                    WHERE capture.incident_evidence_id = %s
                      AND capture.wave = 'B'
                      AND telemetry.structured ->> 'telemetry_type' IS NOT NULL
                    """,
                    (incident_evidence_id,),
                ).fetchall()
            }
            missing_wave_b = sorted(
                set(EXPECTED_WAVE_B_SIGNALS) - wave_b_signals
            )
            require(
                not missing_wave_b,
                f"Validation Evidence is missing validation signal types: {missing_wave_b}",
            )
    except psycopg.errors.UndefinedTable:
        return finish(GATE_ID, BLOCKED, "capture-stage schema is not applied")
    except psycopg.errors.UndefinedColumn:
        return finish(GATE_ID, BLOCKED, "capture-stage schema is not applied")
    except psycopg.OperationalError as error:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {error}")

    a_count, _ = coverage["A"]
    b_count, _ = coverage["B"]
    return finish(
        GATE_ID,
        PASS,
        f"Investigation Evidence {a_count} + Validation Evidence {b_count} "
        "current documents; validation is additive",
    )


if __name__ == "__main__":
    main_guard(run)
