# Lab 3: Reason - Build and deploy the Retrieval agent

Follow **Workshop Studio → Lab 3** for the exact requests, the checks and each
section's **Stuck?** hints. This is the reminder beside your code.

Alex has found his headphones and monitor. Add the chair and check the whole
setup against source records, using the SQL you repaired in Labs 1 and 2.

## Open the Retrieval agent's starting code

Lab 2's handoff installed the starting code. Open [agent.py](agent.py) and find
`create_agent`. It raises `NotImplementedError`. The guide's **Hints** tab shows
how to list the Gateway tools if you'd like to inspect them.

`create_agent` receives the model, five tools, source instructions and
tool-call hooks. It has to return an `Agent` built from them; until it does,
Runtime has nothing to invoke.

## Build and deploy the Retrieval agent

In [agent.py](agent.py), edit only between `LAB3_EDIT_START` and
`LAB3_EDIT_END`. Return a Strands `Agent` with `model=model`, `tools=tools`,
`system_prompt=instructions`, `hooks=hooks` and `callback_handler=None`. Keep
the supplied instructions: they hold the tool order and evidence rules, and the
deploy refuses a prompt without them. Saving changes nothing in Runtime until you
deploy, and until you do, questions wait for it:

```bash
uv run python scripts/deploy_agentcore.py deploy
```

The deployment ends with `Your Retrieval agent is deployed and its SQL
tools are connected through Gateway.`

## Complete Alex's setup, with sources

In **Ask Mosaic**, choose **Complete my setup** in a new conversation. Open a
citation beside a claim about the chair. Read the listing or review to see
what it supports.

## Change a need, then prove the run

Start a new conversation for the guide's 100W question. Then check both saved answers at the shell prompt:

```bash
uv run python scripts/grade_setup_run.py
```

It picks one setup run since Lab 3 started: the newest grounded one, else the newest
that answered. It says which it chose and how many newer runs it passed over, such as
a retry that stopped on HTTP 503, then reads your deployed code, that run and your
newest 100W answer without generating another answer. If you lose the connection during either question, wait
a minute and run the same check. Its `Next:` line tells you whether to wait or which
question to ask again. Use `--run-id <run-id>` to select a particular setup run.
Once the check passes, try your own shopping question in a new conversation.

<details>
<summary>🛠️ Compare with or install the reference answer</summary>

`uv run python scripts/diff.py agent.py` names the lines of your file that differ from the
[reference answer](solution/agent.py), inside and outside the markers, without
printing it, and changes nothing; an instruction you added shows as a difference.
Add `--answer` to see the answer's lines; try the guide's hints first. `uv run python scripts/lab_state.py apply-solution --lab 3`
overwrites your edit with the answer; deploy it, then ask the setup request and
the 100W question yourself and prove them. `uv run python scripts/lab_state.py finish --lab 3`
installs and deploys the answer in one command, after finishing any earlier lab that
is not complete.

</details>
