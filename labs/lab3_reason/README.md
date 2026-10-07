# Lab 3: Reason - Build and deploy the agent

Follow **Workshop Studio → Lab 3** for the exact requests, SQL investigation,
hints and complete checks. This is the reminder beside your code.

## Broken

Start Lab 3 after both SQL labs pass. The starter cannot assemble the agent. Inspect the refusal and discover the supplied Gateway tools using the guide.

## Diagnose

Open [agent.py](agent.py). Identify what `create_agent` must return and how its model, tools, source rules and hooks work together.

## Fix

Edit only `LAB3_AGENT_START` through `LAB3_AGENT_END`. Return a Strands
`Agent` using `model=model`, `tools=tools`, `system_prompt=instructions`,
`hooks=hooks` and `callback_handler=None`. Add one instruction of your own;
preserve the existing source rules and hooks.

## Prove

Save and deploy:

```bash
uv run python scripts/deploy_agentcore.py deploy
```

Run **Playground → Complete my room → Reason**. Save the original run ID.
Inspect separate searches, comparison, final shortlist and citations for the
Logitech headphones, ViewSonic monitor and Steelcase chair. Distinguish listing
features from review experience and unknowns. Complete the guide's changed
requirement follow-up, then prove the **original room run**:

```bash
uv run python scripts/complete_agent.py --run-id <your-run-id>
```

This evaluates your deployed code and actual saved answer without generating
another answer. Deployment alone does not prove completion.


<details>
<summary>🛠️ Recovery and reference answer</summary>

The [reference answer](solution/agent.py) is available for full recovery.
`uv run python scripts/lab_state.py solution --lab 3` overwrites this lab's
edit. Follow the guide to apply/deploy and prove it; recovery is not completion.

</details>
