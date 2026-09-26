"""Assemble the Strands agent that runs in Amazon Bedrock AgentCore Runtime.

The workshop supplies the Bedrock model, bounded SQL tool adapters and execution
hooks. Search, evidence and retrieval-history adapters call AgentCore Gateway;
comparison and cited synthesis use the records those tools return.
"""

from strands import Agent


def create_agent(*, model, tools, instructions: str, hooks) -> Agent:
    """Build an agent that can choose tools and return a supported recommendation."""
    # LAB3_AGENT_START
    return Agent(
        model=model,
        tools=tools,
        system_prompt=instructions,
        hooks=hooks,
        callback_handler=None,
    )
    # LAB3_AGENT_END
