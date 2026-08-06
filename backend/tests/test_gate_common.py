from __future__ import annotations

import time
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


    def test_escape_heavy_quoted_password_does_not_backtrack(self) -> None:
        """An unterminated quoted password must not backtrack exponentially.

        The quoted branch alternated `\\\\.` with a class that also matched the
        backslash, so every `\\&` pair could be consumed two ways. With no closing
        quote the match fails only after trying all of them: measured 1.65ms at 14
        pairs, 23.6ms at 18, and 380ms at 22 on the shipped pattern.

        The DSN reaches this function from the environment, so a malformed value
        stalls the gate rather than failing it.
        """
        for pairs in (18, 24, 30):
            dsn = "host=example.test password='" + ("\\&" * pairs)
            with self.subTest(pairs=pairs):
                start = time.perf_counter()
                redact_dsn(dsn)
                elapsed = time.perf_counter() - start
                self.assertLess(
                    elapsed,
                    0.05,
                    f"redact_dsn took {elapsed * 1000:.1f}ms on {pairs} escape pairs",
                )

    def test_backslash_escaped_quote_stays_inside_the_password(self) -> None:
        """A `\\'` inside a quoted password must not end the quoted run early."""
        self.assertEqual(
            redact_dsn(
                r"user=retrieval_admin password='secret\'s value' "
                "host=example.test dbname=workshop"
            ),
            (
                "user=retrieval_admin password=*** "
                "host=example.test dbname=workshop"
            ),
        )


if __name__ == "__main__":
    unittest.main()
