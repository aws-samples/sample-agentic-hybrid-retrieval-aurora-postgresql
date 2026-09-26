"""Participant-safe messages for an incomplete or unavailable managed agent."""


class AgentSetupError(RuntimeError):
    """An actionable setup problem safe to show without credentials or AWS payloads."""


AGENT_STARTER_MESSAGE = (
    "Your agent is not built yet. Open labs/lab3/agent.py in Code Editor and "
    "complete create_agent with the supplied model, tools, instructions and hooks. "
    "Next: run make deploy-agent, then ask your question again."
)

AGENT_TOOLS_MESSAGE = (
    "Your agent is missing its Mosaic tools. Open labs/lab3/agent.py in Code "
    "Editor and pass the supplied tools to Agent. "
    "Next: run make deploy-agent, then ask your question again."
)
