# Lab 3: Reason - Build and deploy the Retrieval agent

Follow **Workshop Studio → Lab 3** for the exact requests, the checks and each
task's **Stuck?** hints. This is the reminder beside your code.

Alex has found his headphones and monitor. Add the chair and check the whole
setup against source records, using the SQL you repaired in Labs 1 and 2.

## Task 3A: Connect the tools, build the Retrieval agent, deploy it

**See it fail.** Lab 2's handoff installed the Retrieval agent starter and
reported **Your Retrieval agent is not built yet**; `create_agent` raises
`NotImplementedError`. List the Gateway tools your Retrieval agent will get:

```bash
uv run python scripts/deploy_agentcore.py tools
```

**Why.** `create_agent` receives the model, five tools, source instructions
and tool-call hooks. It has to return an `Agent` built
from them; until it does, Runtime has nothing to invoke.

**Build.** In [agent.py](agent.py), edit only between `LAB3_EDIT_START` and
`LAB3_EDIT_END`. Return a Strands `Agent` with `model=model`, `tools=tools`,
`system_prompt=instructions`, `hooks=hooks` and `callback_handler=None`. You
may add one instruction of your own; keep the source rules and hooks. Saving
changes nothing in Runtime until you deploy:

```bash
uv run python scripts/deploy_agentcore.py deploy
```

**Prove it.** The deployment ends with `Your Retrieval agent is deployed and its SQL
tools are connected through Gateway.`

## Task 3B: Complete Alex's setup, change a requirement, prove the run

Ask the guide's setup request from the terminal with
`uv run python scripts/ask_agent.py "..."`. It prints the answer, the plan, the
tool trace, each citation with its quote, the outcome and the **Run ID**. Read
one listing citation and one review citation against the sentences that cite
them, then ask the guide's 100W follow-up the same way. Prove the setup run,
not the follow-up:

```bash
uv run python scripts/complete_agent.py --run-id <your-run-id>
```

It reads your deployed code and the saved run without generating another
answer. Deployment alone does not prove completion.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py` names the lines of your file that differ from the
[reference answer](solution/agent.py), inside and outside the markers, without
printing it, and changes nothing; an instruction you added shows as a difference.
Add `--answer` to see the answer's lines; try the guide's hints first. `uv run python scripts/lab_state.py solution --lab 3`
overwrites your edit with the answer; deploy it, then run the setup request
yourself and prove that run.

</details>
