from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
    )


class GitHookInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "repository"
        self.root.mkdir()
        self.global_config = Path(self.temporary_directory.name) / "gitconfig"
        environment_patch = patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": str(self.global_config)},
        )
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        run(["git", "init", "-q"], cwd=self.root)

        scripts = self.root / "scripts"
        (scripts / "git-hooks").mkdir(parents=True)
        for relative in (
            Path("scripts/install_git_hooks.sh"),
            Path("scripts/git-hooks/pre-push"),
        ):
            target = self.root / relative
            shutil.copy2(REPOSITORY_ROOT / relative, target)
            target.chmod(0o755)

        self.upstream = Path(self.temporary_directory.name) / "git-defender-hooks"
        self.upstream.mkdir()
        self.log = Path(self.temporary_directory.name) / "hook.log"
        for name in ("pre-commit", "pre-push"):
            hook = self.upstream / name
            hook.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                f"printf '%s\\n' {name} >> \"$HOOK_LOG\"\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)

        run(
            ["git", "config", "--global", "core.hooksPath", str(self.upstream)],
            cwd=self.root,
        )

    def test_installer_chains_global_hooks_and_custom_pre_push(self) -> None:
        installer = self.root / "scripts" / "install_git_hooks.sh"
        run([str(installer)], cwd=self.root)
        run([str(installer)], cwd=self.root)

        managed = Path(
            run(
                ["git", "config", "--local", "--get", "core.hooksPath"],
                cwd=self.root,
            ).stdout.strip()
        )
        chained = run(
            [
                "git",
                "config",
                "--local",
                "--get",
                "workbench.chainedHooksPath",
            ],
            cwd=self.root,
        ).stdout.strip()

        self.assertEqual(chained, str(self.upstream))
        self.assertEqual(
            (managed / "pre-commit").resolve(),
            (self.upstream / "pre-commit").resolve(),
        )
        self.assertEqual(
            (managed / "pre-push").resolve(),
            (self.root / "scripts" / "git-hooks" / "pre-push").resolve(),
        )

        env = {**os.environ, "HOOK_LOG": str(self.log)}
        run([str(managed / "pre-commit")], cwd=self.root, env=env)
        deletion = (
            "refs/heads/main "
            "0000000000000000000000000000000000000000 "
            "refs/heads/main "
            "1111111111111111111111111111111111111111\n"
        )
        run(
            [str(managed / "pre-push"), "origin", "unused"],
            cwd=self.root,
            env=env,
            input_text=deletion,
        )

        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines(),
            ["pre-commit", "pre-push"],
        )


if __name__ == "__main__":
    unittest.main()
