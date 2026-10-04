"""Participant-safe messages for an incomplete or unavailable managed agent."""

import re

from service.participant_commands import DEPLOY_AGENT


class AgentSetupError(RuntimeError):
    """An actionable setup problem safe to show without credentials or AWS payloads."""


AGENT_STARTER_MESSAGE = (
    "Your agent is not built yet. Open labs/lab3_reason/agent.py in Code Editor and "
    "complete create_agent with the supplied model, tools, instructions and hooks. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)

AGENT_TOOLS_MESSAGE = (
    "Your agent is missing its Mosaic tools. Open labs/lab3_reason/agent.py in Code "
    "Editor and pass the supplied tools to Agent. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)

AGENT_HOOKS_MESSAGE = (
    "Your agent is missing the supplied execution hooks. Open labs/lab3_reason/agent.py "
    "in Code Editor and pass hooks to Agent. "
    f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
)


def agent_code_message(error: BaseException) -> str:
    """Name a participant's coding mistake without a traceback, URL or long text."""
    if isinstance(error, SyntaxError):
        detail = f"{error.msg} (line {error.lineno})"
    else:
        detail = str(error)
    detail = re.sub(r"\S+://\S+", "[url]", " ".join(detail.split()))[:200]
    return (
        f"Your agent code raised {type(error).__name__}: {detail}. Open "
        "labs/lab3_reason/agent.py in Code Editor and fix that line. "
        f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
    )
