"""A participant's mistake in create_agent must be named, not called "not built yet"."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from strands import Agent

from service import agent as agent_module
from service.agent_setup import (
    AGENT_STARTER_MESSAGE,
    AGENT_TOOLS_MESSAGE,
    AgentSetupError,
)
from service.participant_commands import DEPLOY_AGENT


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "get_settings",
        lambda: SimpleNamespace(agent_model_id="model", aws_region="us-east-1"),
    )
    monkeypatch.setattr(agent_module, "_bedrock_model", lambda *_: Mock())


def participant_agent(monkeypatch, create_agent):
    module = types.ModuleType("labs.lab3_reason.agent")
    module.create_agent = create_agent
    monkeypatch.setitem(sys.modules, "labs.lab3_reason.agent", module)


def test_unimplemented_starter_keeps_the_exact_starter_message(monkeypatch):
    def create_agent(**_):
        raise NotImplementedError

    participant_agent(monkeypatch, create_agent)
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    assert str(raised.value) == AGENT_STARTER_MESSAGE


@pytest.mark.parametrize(
    "mistake,kind",
    [
        (lambda **_: Agent(modle=None), "TypeError"),
        (lambda **_: undefined_name, "NameError"),  # noqa: F821
    ],
)
def test_a_coding_mistake_names_the_error_file_and_command(monkeypatch, mistake, kind):
    participant_agent(monkeypatch, mistake)
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    message = str(raised.value)
    assert message != AGENT_STARTER_MESSAGE
    assert not message.startswith("Your agent is not built yet.")
    assert kind in message
    assert "labs/lab3_reason/agent.py" in message
    assert DEPLOY_AGENT in message
    assert "Traceback" not in message


def write_participant_file(monkeypatch, tmp_path, source):
    import labs.lab3_reason

    (tmp_path / "agent.py").write_text(source)
    monkeypatch.setattr(labs.lab3_reason, "__path__", [str(tmp_path)])
    monkeypatch.delitem(sys.modules, "labs.lab3_reason.agent", raising=False)


def test_a_syntax_error_in_the_file_is_named(monkeypatch, tmp_path):
    write_participant_file(monkeypatch, tmp_path, "x = 1\ndef create_agent(:\n")
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    message = str(raised.value)
    assert "SyntaxError" in message and "line 2" in message
    assert DEPLOY_AGENT in message


def test_an_import_error_in_the_file_is_named(monkeypatch, tmp_path):
    write_participant_file(monkeypatch, tmp_path, "from strands import Agnt\n")
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    assert "ImportError" in str(raised.value) and "Agnt" in str(raised.value)


def test_missing_tools_keep_the_exact_tools_message(monkeypatch):
    participant_agent(
        monkeypatch,
        lambda **kwargs: Agent(
            model=kwargs["model"], hooks=kwargs["hooks"], callback_handler=None
        ),
    )
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    assert str(raised.value) == AGENT_TOOLS_MESSAGE


def test_omitting_the_supplied_hooks_is_detected(monkeypatch):
    participant_agent(
        monkeypatch,
        lambda **kwargs: Agent(
            model=kwargs["model"],
            tools=kwargs["tools"],
            system_prompt=kwargs["instructions"],
            callback_handler=None,
        ),
    )
    with pytest.raises(AgentSetupError) as raised:
        agent_module.build_agent()
    message = str(raised.value)
    assert "hooks" in message and "labs/lab3_reason/agent.py" in message
    assert DEPLOY_AGENT in message
    assert not message.startswith(
        ("Your agent is not built yet.", "Your agent is missing its Mosaic tools.")
    )


def test_the_supplied_starter_solution_builds(monkeypatch):
    monkeypatch.delitem(sys.modules, "labs.lab3_reason.agent", raising=False)
    from labs.lab3_reason.solution.agent import create_agent

    participant_agent(monkeypatch, create_agent)
    assert agent_module.build_agent().tool_names
