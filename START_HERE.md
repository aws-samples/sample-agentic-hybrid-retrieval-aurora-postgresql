# Start here

Begin in Workshop Studio with **Getting started**; the **Overview** before it
is optional. Every step runs in this terminal: you read the catalog's data,
indexes and search functions in `psql`, then save Lab 1's failing search. Keep the guide and Code
Editor side by side in two browser windows. Mosaic, the store at **MosaicURL**,
shows the same results the terminal prints; the guide says when a lab uses it.

Each lab is two tasks, and every task runs the same way:

1. **See it fail.** Repeat the guide's exact request and filters, and keep them
   fixed, so the before and after compare the same thing.
2. **Why.** Read the record that explains the failure before you open any code.
3. **Build.** Edit only the marked block, then apply the SQL or deploy the
   Retrieval agent. Saving the file changes nothing until you do.
4. **Prove it.** Repeat the identical request and finish on the guide's check.

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

The lab READMEs are short reminders. The guide has the exact requests, the
checks, and a **Stuck?** block in every task with hints, a prompt for the
coding coach and the answer. Your saved runs are in `.local/lab-N/`. To see which
lines of your lab files differ from the reference answer without changing
anything, run `uv run python scripts/diff.py`; it does not print the answer.
`uv run python scripts/diff.py --answer` does, so try the hints first.

In Lab 2, Task 2A repairs the rank contribution and Task 2B reads what
reranking changed and compares three settings. In Lab 3, copy the
**Retrieval agent record** ID of your original setup run before you ask any follow-up:
completion checks that run.

After the labs, open **Playground → Take this retrieval into your own agent**
and choose **Download the skill** to keep the Hybrid Agentic Search skill. For
the source layout, see [the repository map](docs/index.md) and
[the agent guidance](AGENTS.md).
