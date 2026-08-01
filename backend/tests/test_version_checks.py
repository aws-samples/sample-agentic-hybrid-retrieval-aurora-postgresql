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
                self.assertEqual(parser(b"18.4 (Homebrew)"), (18, 4))


if __name__ == "__main__":
    unittest.main()
