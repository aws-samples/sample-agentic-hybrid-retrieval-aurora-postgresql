"""Editor navigation must open the real lab files and a root-owned terminal."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

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
    assert task["args"] == ["-l"]
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
