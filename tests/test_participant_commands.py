"""Participants type one form of every command: the `uv run` script the guides show.

Two gates. Every participant-facing surface is free of the Make targets that
wrap those scripts, so a terminal message, a proof detail and the Playground
never name a command the guide does not. And every command in
`service.participant_commands` names a script and an action that exist, so a
renamed action fails here rather than in a participant's terminal.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from service import participant_commands as commands

ROOT = Path(__file__).resolve().parents[1]

PARTICIPANT_MAKE = re.compile(
    r"\bmake (?:lab-status|start-lab|reset-lab|solution-lab|validate-lab|"
    r"db-apply-search-functions|agent-tools|deploy-agent|verify-agent|"
    r"complete-lab-3|restart-lab-api)"
)

PARTICIPANT_SCRIPTS = (
    "apply_search_functions.py",
    "complete_agent.py",
    "configure_retrieval_database.py",
    "deploy_agentcore.py",
    "lab_entry.py",
    "lab_exercise.py",
    "lab_state.py",
    "lab_terminal.py",
    "validate_lab.py",
)
PARTICIPANT_DOCS = ("README.md", "START_HERE.md", "workshop.md", "AGENTS.md")


def participant_surfaces(root: Path = ROOT) -> list[Path]:
    ui = [
        path
        for path in (root / "ui" / "src").rglob("*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    ]
    return [
        *sorted((root / "service").glob("*.py")),
        *(root / "scripts" / name for name in PARTICIPANT_SCRIPTS),
        *sorted(
            path
            for path in (root / "labs").rglob("*")
            if path.suffix in {".py", ".sql", ".md"} and "__pycache__" not in path.parts
        ),
        *(root / name for name in PARTICIPANT_DOCS),
        *sorted(ui),
    ]


def make_mentions(paths: list[Path], root: Path = ROOT) -> list[str]:
    return [
        f"{path.relative_to(root)}:{number}: {match.group(0)}"
        for path in paths
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for match in PARTICIPANT_MAKE.finditer(line)
    ]


def test_participant_surfaces_name_the_uv_command_not_a_make_target() -> None:
    found = make_mentions(participant_surfaces())
    assert not found, (
        "Participant command rule: found Make targets on participant surfaces; "
        "fix: use the service.participant_commands form.\n" + "\n".join(found)
    )


def test_the_gate_sees_a_make_target_in_a_message(tmp_path: Path) -> None:
    """Red at birth, kept as a permanent fixture."""
    message = tmp_path / "message.py"
    message.write_text('DETAIL = "Next: run make deploy-agent, then retry."\n')

    assert make_mentions([message], tmp_path) == ["message.py:1: make deploy-agent"]


def _commands() -> list[str]:
    return [
        commands.STATUS,
        commands.APPLY_SQL,
        commands.LIST_TOOLS,
        commands.DEPLOY_AGENT,
        commands.VERIFY_AGENT,
        commands.start(1),
        commands.reset(2),
        commands.solution(3),
        commands.validate(1),
        commands.complete_lab_3("RUN"),
    ]


@pytest.mark.parametrize("command", _commands())
def test_each_command_names_a_script_and_an_action_that_exist(command: str) -> None:
    words = shlex.split(command)
    assert words[:3] == ["uv", "run", "python"]
    script = ROOT / words[3]
    assert script.is_file(), f"{command}: {words[3]} does not exist"
    if len(words) == 4:
        return
    usage = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        timeout=120,
    )
    assert usage.returncode == 0, usage.stderr[-2000:]
    for word in words[4:]:
        if word.startswith("-") or not word.isalpha():
            if word.startswith("--"):
                assert word in usage.stdout, f"{command}: {word} is not an option"
            continue
        assert word in usage.stdout, f"{command}: {word} is not an action"


UI_COMMANDS = ROOT / "ui" / "src" / "participantCommands.ts"


def ui_commands(text: str) -> dict[str, str]:
    """The UI's copies, read from its constants and its validate template."""
    found = dict(re.findall(r'export const (\w+) = "([^"]+)";', text))
    template = re.search(r"return `([^`]+)\$\{lab\}`;", text)
    if template:
        found["validate"] = template.group(1) + "{lab}"
    return found


def test_the_ui_prints_the_same_commands_as_the_service() -> None:
    ui = ui_commands(UI_COMMANDS.read_text())
    assert ui == {
        "APPLY_SQL": commands.APPLY_SQL,
        "DEPLOY_AGENT": commands.DEPLOY_AGENT,
        "VERIFY_AGENT": commands.VERIFY_AGENT,
        "validate": commands.validate(1).removesuffix("1") + "{lab}",
    }, (
        f"Participant command rule: {UI_COMMANDS.relative_to(ROOT)} holds {ui}; "
        "fix: copy the strings from service/participant_commands.py exactly."
    )


def test_the_ui_command_gate_sees_a_drifted_command() -> None:
    drifted = UI_COMMANDS.read_text().replace(
        "apply_search_functions.py", "apply_sql.py"
    )
    assert ui_commands(drifted)["APPLY_SQL"] != commands.APPLY_SQL
