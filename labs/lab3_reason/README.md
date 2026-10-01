# Lab 3: Reason

Build and deploy an agent that explains its choices with sources. Follow
**Workshop Studio → Lab 3** beside this folder. In the participant workspace,
this is **03 — Reason**. The file you edit is [agent.py](agent.py).

## Broken

Start the lab after completing Retrieve, Rank and Re-rank. The starter cannot assemble
the agent. The workshop already supplies the Bedrock model, SQL tools behind
AgentCore Gateway, source rules and execution hooks.

## Diagnose

Inspect the supplied components and the saved refusal before changing code.
Identify what the `create_agent` factory must return and what evidence the
running agent will need for Alex's question. The guide leads the tool discovery
and explains how retrieval, comparison and citations work together.

## Fix

Complete `create_agent` between `LAB3_AGENT_START` and `LAB3_AGENT_END` using
the supplied values:

| Agent argument | Supplied value |
|---|---|
| `model` | `model` |
| `tools` | `tools` |
| `system_prompt` | `instructions` |
| `hooks` | `hooks` |
| `callback_handler` | `None` |

The guide invites one instruction of your own inside that block. Keep the
existing source rules and execution hooks.

## Prove

Deploy the edited agent:

```bash
uv run python scripts/deploy_agentcore.py deploy
```

Ask **Complete my room** in Mosaic: bring back Alex’s Bose headphones and ViewSonic monitor, then add the Steelcase chair. Inspect a focused search for each, all three in the comparison and final shortlist, and their cited sources. Then
save your run ID. Complete the changed-requirement follow-up, then check the
original saved run with the guide's completion command:

```bash
uv run python scripts/complete_agent.py --run-id <your-run-id>
```

That check evaluates your actual run; it does not generate a replacement answer.
A successful deployment proves connectivity, not participant completion.

<details>
<summary>Recovery and reference answer</summary>

The [reference answer](solution/agent.py) is available when you want full
recovery. `uv run python scripts/lab_state.py solution --lab 3` overwrites the
exercise with that answer. Follow the guide to deploy and prove it; recovery
alone is not completion.

</details>
