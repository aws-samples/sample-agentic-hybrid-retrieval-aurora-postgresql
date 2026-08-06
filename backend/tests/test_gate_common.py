from __future__ import annotations

import unittest

from gates._common import redact_dsn


class GateDsnRedactionTests(unittest.TestCase):
    def test_url_password_is_redacted(self) -> None:
        self.assertEqual(
            redact_dsn(
                "postgresql://retrieval_admin:secret@example.test:5432/workshop"
            ),
            "postgresql://retrieval_admin:***@example.test:5432/workshop",
        )

    def test_unquoted_keyword_password_is_redacted(self) -> None:
        self.assertEqual(
            redact_dsn(
                "user=retrieval_admin password=secret,with,punctuation "
                "host=example.test dbname=workshop"
            ),
            (
                "user=retrieval_admin password=*** "
                "host=example.test dbname=workshop"
            ),
        )

    def test_quoted_keyword_password_is_redacted(self) -> None:
        self.assertEqual(
            redact_dsn(
                "user=retrieval_admin password='secret with spaces' "
                "host=example.test dbname=workshop"
            ),
            (
                "user=retrieval_admin password=*** "
                "host=example.test dbname=workshop"
            ),
        )


if __name__ == "__main__":
    unittest.main()
