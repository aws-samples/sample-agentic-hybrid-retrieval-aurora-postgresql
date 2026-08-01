from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INCIDENT_FILES = {
    "00_setup.sql",
    "10_unsafe_index.sql",
    "20_blocked_writer.sql",
    "30_observe_unsafe.sql",
    "40_safe_writer.sql",
    "50_concurrent_index.sql",
    "60_observe_safe.sql",
    "70_verify.sql",
    "99_cleanup.sql",
}


class ReleaseArtifactScriptTests(unittest.TestCase):
    def test_archive_requires_every_incident_script(self) -> None:
        source = (
            REPOSITORY_ROOT / "scripts" / "build_source_archive.sh"
        ).read_text(encoding="utf-8")

        for filename in INCIDENT_FILES:
            self.assertIn(f"labs/incident/{filename}", source)
        self.assertIn(
            "seed/artifacts/hybrid-retrieval-seed-v2.dump.sha256",
            source,
        )
        self.assertIn("sha256sum", source)
        self.assertIn("shasum", source)

    def test_dump_requires_explicit_opt_in_before_connecting(self) -> None:
        env = os.environ.copy()
        env["DATABASE_URL"] = "postgresql://example.invalid/retrieval"
        env.pop("ALLOW_SEED_DUMP", None)

        completed = subprocess.run(
            ["bash", "seed/dump.sh"],
            cwd=REPOSITORY_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("ALLOW_SEED_DUMP=1", completed.stderr)

    def test_dump_rejects_server_reported_live_database_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            psql = bin_dir / "psql"
            pg_dump = bin_dir / "pg_dump"
            psql.write_text(
                "#!/usr/bin/env bash\nprintf 'retrieval\\n'\n",
                encoding="utf-8",
            )
            pg_dump.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
            psql.chmod(0o755)
            pg_dump.chmod(0o755)

            env = os.environ.copy()
            env["DATABASE_URL"] = "postgresql://ignored/retrieval"
            env["ALLOW_SEED_DUMP"] = "1"
            env["PATH"] = f"{bin_dir}:{env['PATH']}"

            completed = subprocess.run(
                ["bash", "seed/dump.sh"],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing to dump database 'retrieval'", completed.stderr)
        self.assertIn("must end in '_test'", completed.stderr)

    def test_restore_rejects_tampered_dump_before_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            artifact = temp_path / "seed.dump"
            artifact.write_bytes(b"tampered")
            artifact.with_suffix(".dump.sha256").write_text(
                "0" * 64 + "\n",
                encoding="ascii",
            )
            pg_restore = temp_path / "pg_restore"
            pg_restore.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
            pg_restore.chmod(0o755)

            env = os.environ.copy()
            env["DATABASE_URL"] = "postgresql://example.invalid/retrieval"
            env["PATH"] = f"{temp_path}:{env['PATH']}"

            completed = subprocess.run(
                ["bash", "seed/load.sh", str(artifact)],
                cwd=REPOSITORY_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("seed artifact checksum mismatch", completed.stderr)


if __name__ == "__main__":
    unittest.main()
