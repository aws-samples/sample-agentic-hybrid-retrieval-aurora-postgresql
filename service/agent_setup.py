"""Participant-safe messages for an incomplete or unavailable managed agent."""

import re

from service.participant_commands import DEPLOY_AGENT


class AgentSetupError(RuntimeError):
    """An actionable setup problem safe to show without credentials or AWS payloads."""


AGENT_STARTER_MESSAGE = (
    "Your Retrieval agent is not built yet. Open labs/lab3_reason/agent.py in Code Editor and "
    "complete create_agent with the supplied model, tools, instructions and hooks. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)

#: How the starting code misses the Lab 3 contract, as `lab3_contract_problem` says it.
AGENT_NOT_BUILT = "create_agent still raises NotImplementedError"


def agent_setup_message(problem: str) -> str:
    """The message for one way `agent.py` misses the Lab 3 contract.

    The starting code keeps the message Lab 2's hand-off printed; any other gap is
    named, so an assembled agent whose prompt dropped the supplied instructions is
    not told it was never built.
    """
    if problem == AGENT_NOT_BUILT:
        return AGENT_STARTER_MESSAGE
    return (
        f"Your Retrieval agent is not ready: in labs/lab3_reason/agent.py, {problem}. "
        f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
    )


AGENT_TOOLS_MESSAGE = (
    "Your Retrieval agent is missing its Mosaic tools. Open labs/lab3_reason/agent.py in Code "
    "Editor and pass the supplied tools to Agent. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)

AGENT_HOOKS_MESSAGE = (
    "Your Retrieval agent is missing the supplied execution hooks. Open labs/lab3_reason/agent.py "
    "in Code Editor and pass hooks to Agent. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)


def agent_code_message(error: BaseException) -> str:
    """Name a participant's coding mistake without a traceback, URL or long text."""
    if isinstance(error, SyntaxError):
        line = f"line {error.lineno}"
        detail = error.msg if line in error.msg else f"{error.msg} ({line})"
    else:
        detail = str(error)
    detail = re.sub(r"\S+://\S+", "[url]", " ".join(detail.split()))[:200]
    return (
        f"Your Retrieval agent code raised {type(error).__name__}: {detail}. Open "
        "labs/lab3_reason/agent.py in Code Editor and fix that line. "
        f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
    )
