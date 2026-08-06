from __future__ import annotations

import unittest

from gates import rls_enforcement


class _ClassificationCursor:
    def __init__(self) -> None:
        self.query = ""

    def execute(self, query: str) -> None:
        self.query = query

    def fetchall(self) -> list[tuple[str, str]]:
        return [("TEL-CAPTURE-W01", "evidence-id")]

    def fetchone(self) -> tuple[int, ...]:
        if self.query == rls_enforcement.CLASSIFICATION_ORACLE_SQL:
            return (23, 23, 0, 0, 0)
        return (23,)


class RlsClassificationOracleTests(unittest.TestCase):
    def test_oracle_columns_keep_the_sql_select_order(self) -> None:
        measured = rls_enforcement._measure_classification(
            _ClassificationCursor()
        )

        self.assertEqual(
            measured["oracle"],
            {
                "carries": 23,
                "source_backed": 23,
                "should_be_restricted": 0,
                "should_be_workshop": 0,
                "provenance_errors": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
