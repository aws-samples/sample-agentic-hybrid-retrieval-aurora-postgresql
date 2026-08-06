from __future__ import annotations

import os
import subprocess
import sys
import unittest


class ConfigTests(unittest.TestCase):
    def test_process_database_url_overrides_dotenv(self) -> None:
        expected = "postgresql://override.invalid/example"
        environment = dict(os.environ)
        environment["DATABASE_URL"] = expected
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from backend.app.config import get_settings; "
                    "print(get_settings().database_url)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertEqual(completed.stdout.strip(), expected)

    def test_retired_database_insights_template_is_ignored(self) -> None:
        environment = dict(os.environ)
        environment["WORKBENCH_DBI_URL_TEMPLATE"] = (
            "https://console.example.invalid/database-insights"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from backend.app.config import get_settings; "
                    "print(hasattr(get_settings(), 'workbench_dbi_url_template'))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertEqual(completed.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
