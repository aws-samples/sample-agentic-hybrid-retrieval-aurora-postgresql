"""A tool error that a retry cannot fix must stop the Strands loop, visibly."""

from typing import Any

import pytest
from strands import Agent, tool
from strands.models.model import Model

from service.agent import _loop_error, _StopOnRunErrors
from service.agent_setup import AgentSetupError
from service.model_runtime import ModelRuntimeError


class ScriptedModel(Model):
    """Calls the one tool, then answers in text if the loop gives it the result."""

    def __init__(self) -> None:
        self.calls = 0

    def update_config(self, **_: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, *_: Any, **__: Any):
        raise NotImplementedError
        yield

    async def stream(self, *_: Any, **__: Any):
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if self.calls == 1:
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "t1", "name": "lookup"}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": "The lookup failed."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def run(error: Exception, hooks: list[Any]) -> ScriptedModel:
    @tool
    def lookup() -> str:
        """Look something up."""
        raise error

    model = ScriptedModel()
    Agent(model=model, tools=[lookup], hooks=hooks, callback_handler=None)("go")
    return model


@pytest.mark.parametrize(
    "error",
    [
        AgentSetupError("The deployed SQL tools differ from your workspace."),
        ModelRuntimeError("Bedrock could not complete the model request."),
    ],
)
def test_an_unfixable_tool_error_stops_the_run(error):
    with pytest.raises(Exception) as raised:
        run(error, [_StopOnRunErrors()])
    assert _loop_error(raised.value) is error


def test_an_ordinary_tool_error_still_goes_back_to_the_model():
    model = run(ValueError("no rows for that filter"), [_StopOnRunErrors()])
    assert model.calls == 2


def test_without_the_hook_strands_hands_the_setup_error_to_the_model():
    model = run(AgentSetupError("deploy first"), [])
    assert model.calls == 2


def test_a_setup_error_keeps_its_message_to_the_participant():
    from service.agent import ProductDiscoveryAgent
    from service.models import AgentRequest, SearchFilters

    message = "The deployed SQL tools differ from your workspace. Next: deploy."
    request = AgentRequest(question="Find a quiet keyboard.", filters=SearchFilters())
    with pytest.raises(AgentSetupError, match="differ from your workspace"):
        ProductDiscoveryAgent()._response(
            request, {"answer_of_record": None}, None, AgentSetupError(message)
        )


def test_deploy_names_a_syntax_error_in_the_participant_agent(tmp_path):
    from scripts.deploy_agentcore import not_ready_message

    agent_file = tmp_path / "agent.py"
    agent_file.write_text('x = "unterminated\n', encoding="utf-8")
    message = not_ready_message(agent_file)
    assert "SyntaxError" in message and message.count("line 1") == 1
    agent_file.write_text("raise NotImplementedError\n", encoding="utf-8")
    assert "complete create_agent" in not_ready_message(agent_file)
