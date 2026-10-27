# Start here

Begin in Workshop Studio with **Getting started**; the **Overview** before it
is optional. Run Getting started's catalog readiness check in this terminal,
then save Lab 1's failing search. Keep the guide and Code
Editor side by side in two browser windows. Mosaic, the store at **MosaicURL**,
shows the same results the terminal prints; the guide says when a lab uses it.

Each lab's main page shows **Concepts** and its animation. Select **Start exercise**
for the required steps; each command is followed by a screenshot of what you should
see. **Go deeper (Optional)**, after Wrap-up, holds extra reading and experiments.
Each exercise follows the same flow:

1. Send the guide's exact request and filters, and keep them fixed, so the
   before and after compare the same thing.
2. Read the record that explains the failure before you open any code.
3. Edit only the exercise, then apply the SQL or deploy the Retrieval
   agent. Saving the file changes nothing until you do.
4. Repeat the identical request and finish on the guide's check.

| Explorer group | Lab | File to edit |
|---|---|---|
| **01 - Retrieve** | Debug hybrid search | [hybrid_search.sql](labs/lab1_retrieve/hybrid_search.sql) |
| **02 - Rank and re-rank** | Tune rank fusion and reranking | [rrf_contribution.sql](labs/lab2_rank/rrf_contribution.sql) |
| **03 - Reason** | Build and deploy the Retrieval agent | [agent.py](labs/lab3_reason/agent.py) |

**04 - Explore Mosaic source** is the whole repository; the three groups above
it are shortcuts to the same files. Every terminal starts at the repository
root. If the groups are missing, open
[Mosaic.code-workspace](Mosaic.code-workspace) with
**File → Open Workspace from File…**.

Claude Code runs in this terminal as a coding coach: type `claude`, then paste the
**Coach** prompt from a **Stuck?** block.

The lab READMEs are short reminders. The guide has the exact requests, the
checks, and a **Stuck?** block wherever you edit, with hints, a prompt for the
coding coach and the answer. Your saved runs are in `.local/lab-N/`. To see which
lines of your lab files differ from the reference answer without changing
anything, run `uv run python scripts/diff.py`; it does not print the answer.
`uv run python scripts/diff.py --answer` does, so try the hints first.

In Lab 2 you repair the rank contribution, then read what reranking changed
and compare three settings; `advance --lab 2` then proves
Lab 2 and prepares Lab 3. In Lab 3, deploy your Retrieval agent, ask Alex's
setup request with `scripts/ask_agent.py`, then run
`uv run python scripts/complete_agent.py`: it checks your newest setup run.

After the labs, open **Playground → Use it in your own agent** and choose
**Download the agent skill** to keep the Hybrid Agentic Search skill, or
**Download the SQL and guide** to adapt the search to your own data. For
the source layout, see [the repository map](docs/index.md) and
[the agent guidance](AGENTS.md).
