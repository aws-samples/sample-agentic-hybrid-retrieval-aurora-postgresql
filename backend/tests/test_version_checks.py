from __future__ import annotations

import unittest

from backend.scripts import check_pgvector, check_postgres, doctor


class VersionTupleTests(unittest.TestCase):
    def test_version_checks_accept_sql_ascii_bytes(self) -> None:
        for parser in (
            check_postgres.version_tuple,
            check_pgvector.version_tuple,
            doctor.version_tuple,
        ):
            with self.subTest(parser=parser.__module__):
                self.assertEqual(parser(b"18.3 (Homebrew)"), (18, 3))

    def test_postgres_test_targets_are_aurora_or_local_only(self) -> None:
        self.assertEqual(
            check_postgres.target_kind(
                host="cluster.us-east-1.rds.amazonaws.com",
                is_aurora=True,
            ),
            "aurora",
        )
        self.assertEqual(
            check_postgres.target_kind(host="127.0.0.1", is_aurora=False),
            "local",
        )
        self.assertEqual(
            check_postgres.target_kind(
                host="postgres.example.com",
                is_aurora=False,
            ),
            "unsupported-remote",
        )

    def test_rds_region_is_derived_from_the_endpoint(self) -> None:
        self.assertEqual(
            check_postgres.rds_region(
                "example.cluster-abc.us-east-1.rds.amazonaws.com"
            ),
            "us-east-1",
        )
        self.assertIsNone(check_postgres.rds_region("localhost"))


if __name__ == "__main__":
    unittest.main()
