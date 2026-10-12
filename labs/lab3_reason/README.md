# Lab 3: Reason - Build and deploy the agent

Follow **Workshop Studio → Lab 3** for the exact requests, the checks and each
task's **Stuck?** hints. This is the reminder beside your code.

## Task 3A: Connect the tools, build the agent, deploy it

**See it fail.** Start the lab and list the Gateway tools your agent will get:

```bash
uv run python scripts/lab_state.py start --lab 3
uv run python scripts/deploy_agentcore.py tools
```

**Playground → Complete my setup → Run Mosaic** answers **Your agent is not
built yet**.

**Why.** `create_agent` receives the model, the three Gateway tools, the source
rules as instructions and the citation hooks. It has to return an `Agent` built
from them; until it does, Runtime has nothing to invoke.

**Build.** In [agent.py](agent.py), edit only between `LAB3_AGENT_START` and
`LAB3_AGENT_END`. Return a Strands `Agent` with `model=model`, `tools=tools`,
`system_prompt=instructions`, `hooks=hooks` and `callback_handler=None`. You
may add one instruction of your own; keep the source rules and hooks. Saving
changes nothing in Runtime until you deploy:

```bash
uv run python scripts/deploy_agentcore.py deploy
```

**Prove it.** The deployment ends with `Your agent is deployed and its SQL
tools are connected through Gateway.`

## Task 3B: Complete Alex's setup, change a requirement, prove the run

Run **Playground → Complete my setup → Run Mosaic** and copy the **Agent record**
ID before anything else. Read the answer against its records: a listing and a
review for each of the headphones, the monitor and the chair. Then ask
**Ask Mosaic** the guide's 100W follow-up about the monitor. Prove the
**original setup run**:

```bash
uv run python scripts/complete_agent.py --run-id <your-run-id>
```

It reads your deployed code and the saved run without generating another
answer. Deployment alone does not prove completion.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/lab_state.py diff --lab 3` compares your marked block
with the [reference answer](solution/agent.py) and changes nothing; an
instruction you added shows as a difference. It shows the answer, so try the
guide's hints first. `uv run python scripts/lab_state.py solution --lab 3`
overwrites your edit with the answer; deploy it, then run the setup request
yourself and prove that run.

</details>
