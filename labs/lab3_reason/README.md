# Lab 3: Reason

Alex wants a monitor and a chair compared with sources. The workshop supplies
the Bedrock model, the SQL tools behind AgentCore Gateway, the source rules and
the execution hooks. The starter cannot assemble the agent that uses them.

## What you edit

`agent.py`, function `create_agent`, between `LAB3_AGENT_START` and
`LAB3_AGENT_END`. Return a Strands `Agent` built from the supplied values:

| Agent argument | Value |
|---|---|
| `model` | `model` |
| `tools` | `tools` |
| `system_prompt` | `instructions` |
| `hooks` | `hooks` |
| `callback_handler` | `None` |

The guide invites one instruction of your own, added to `instructions` inside
the marked block. Keep the existing source rules.

## Deploy and prove

```bash
uv run python scripts/deploy_agentcore.py deploy
uv run python scripts/complete_agent.py --run-id <your-run-id>
```

Ask Alex's question in **Playground → Reason** first and save the run ID. The
final command checks that saved run; it does not generate a new answer.

## Reference answer

[`solution/agent.py`](solution/agent.py). To install it,
`uv run python scripts/lab_state.py solution --lab 3` overwrites your edit.
