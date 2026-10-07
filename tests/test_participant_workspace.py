"""Editor navigation must open the real lab files and a root-owned terminal."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from service.lab_files import LAB_FILES

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "deploy/mosaic-bootstrap.sh"
WORKSPACE = ROOT / "Mosaic.code-workspace"


def test_workspace_roots_are_the_production_lab_directories():
    folders = json.loads(WORKSPACE.read_text())["folders"]
    assert [folder["name"] for folder in folders] == [
        "01 - Retrieve",
        "02 - Rank and re-rank",
        "03 - Reason",
        "04 - Explore Mosaic source",
    ]
    for folder, exercise in zip(folders[:3], LAB_FILES.values(), strict=True):
        assert (ROOT / folder["path"] / exercise.name).samefile(ROOT / exercise)
    assert (ROOT / folders[-1]["path"]).samefile(ROOT)


def test_bootstrap_opens_the_workspace_and_one_root_terminal(tmp_path):
    script = BOOTSTRAP.read_text()
    assert f'--default-workspace "$REPO/{WORKSPACE.name}"' in script
    task_json = re.search(
        r'cat >"\$REPO/\.vscode/tasks.json" <<\'EOF\'\n(.*?)\nEOF',
        script,
        re.DOTALL,
    )
    assert task_json, "root terminal task missing; restore the folderOpen task"
    tasks = json.loads(task_json[1])["tasks"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["runOptions"]["runOn"] == "folderOpen"
    assert task["options"]["cwd"] == "${workspaceFolder}"
    assert task["args"] == ["-l", "${workspaceFolder}/deploy/open-workshop-terminal.sh"]
    assert all(
        not (ROOT / path.parent / ".vscode/tasks.json").exists()
        for path in LAB_FILES.values()
    )

    (tmp_path / ".vscode").mkdir()
    (tmp_path / WORKSPACE.name).write_bytes(WORKSPACE.read_bytes())
    settings_code = re.search(
        r"<<'EDITOR_SETTINGS'\n(.*?)\nEDITOR_SETTINGS", script, re.DOTALL
    )
    assert settings_code, "legacy folder settings generator missing"
    subprocess.run(
        [sys.executable, "-", str(tmp_path)],
        input=settings_code[1],
        text=True,
        check=True,
    )
    generated = json.loads((tmp_path / ".vscode/settings.json").read_text())
    expected = json.loads(WORKSPACE.read_text())["settings"]
    assert (
        expected["terminal.integrated.cwd"]
        == "${workspaceFolder:04 - Explore Mosaic source}"
    )
    expected["terminal.integrated.cwd"] = "${workspaceFolder}"
    assert generated == expected


@pytest.mark.parametrize("first_open_succeeds", [True, False])
def test_terminal_opens_at_root_and_retries_welcome(tmp_path, first_open_succeeds):
    root = tmp_path / "checkout with spaces"
    lab = root / "labs/lab3_reason"
    lab.mkdir(parents=True)
    (root / "deploy").mkdir()
    launcher = root / "deploy/open-workshop-terminal.sh"
    launcher.write_bytes((ROOT / "deploy/open-workshop-terminal.sh").read_bytes())
    (root / "START_HERE.md").write_text("Welcome")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    code = bin_dir / "code"
    code.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" >> "$PROBE_CODE"\nexit "$PROBE_EXIT"\n'
    )
    shell = bin_dir / "bash"
    shell.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$PROBE_SHELL"\n')
    code.chmod(0o755)
    shell.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PROBE_CODE": str(tmp_path / "code.log"),
        "PROBE_SHELL": str(tmp_path / "shell.log"),
        "PROBE_EXIT": "0" if first_open_succeeds else "1",
    }

    def launch():
        subprocess.run(["/bin/bash", str(launcher)], cwd=lab, env=env, check=True)
        assert (tmp_path / "shell.log").read_text().splitlines() == [str(root), "-l"]
        assert not (root / "learning-notes.md").exists()
        assert not (lab / "learning-notes.md").exists()

    launch()
    marker = root / ".local/code-editor-started"
    assert marker.exists() == first_open_succeeds
    env["PROBE_EXIT"] = "0"
    launch()
    assert marker.exists()
    launch()
    calls = (tmp_path / "code.log").read_text().splitlines()
    expected = [str(root), "--reuse-window", str(root / "START_HERE.md")]
    assert calls == expected * (1 if first_open_succeeds else 2)
