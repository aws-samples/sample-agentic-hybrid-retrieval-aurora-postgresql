# Start here

> Outside a workshop event? Start with the [README](README.md) and
> [Run Mosaic in your own account](docs/run-in-your-own-account.md); this page assumes an
> event's prepared account.

Begin in Workshop Studio with **Getting started**; the **Overview** before it
is optional. Run Getting started's catalog readiness check in this terminal,
then save Lab 1's failing search. Keep the guide and Code
Editor side by side in two browser windows. Mosaic, the store at **MosaicURL**,
shows the same results the terminal prints; the guide says when a lab uses it.

Each lab's main page shows **Concepts** and its animation. Select **Next**
for the required steps; each command is followed by a screenshot of what you should
see. **Go deeper (Optional)**, after Wrap-up, holds extra reading and experiments.
Each exercise follows the same flow:

1. Open the lab's file in Code Editor and read the part the guide points to.
2. Use the guide's exact request and filters to see what goes wrong, and keep them
   fixed so the before and after compare the same thing. Find the cause before you edit.
3. Edit only the exercise, then apply the SQL or deploy the Retrieval
   agent. Saving the file changes nothing until you do.
4. Repeat the identical request and finish on the guide's check.

| Explorer group | Lab | File to edit |
|---|---|---|
| **01 - Retrieve** | Debug hybrid search | [hybrid_search.sql](labs/lab1_retrieve/hybrid_search.sql) |
| **02 - Rank and rerank** | Tune rank fusion and reranking | [rrf_contribution.sql](labs/lab2_rank/rrf_contribution.sql) |
| **03 - Reason** | Build and deploy the Retrieval agent | [agent.py](labs/lab3_reason/agent.py) |

**04 - Explore Mosaic source** is the whole repository; the three groups above
it are shortcuts to the same files. Every terminal starts at the repository
root. If the groups are missing, open
[Mosaic.code-workspace](Mosaic.code-workspace) with
**File → Open Workspace from File…**.

Claude Code runs in the terminal as a coding coach: open a second terminal with **+** so
`psql` stays open, type `claude`, then paste the first **Coach** prompt from a **Stuck?**
block. It explains and gives a hint; the second prompt makes the change. It writes each
answer fresh, so when its steps differ from the guide, follow the guide.

The lab READMEs are short reminders. The guide has the exact requests, the
checks, and a **Stuck?** block wherever you edit, with hints, two prompts for the
coding coach and the answer. Your saved runs are in `.local/lab-N/`. To see which
lines of your lab files differ from the reference answer without changing
anything, run `uv run python scripts/diff.py`; it does not print the answer.
`uv run python scripts/diff.py --answer` does, so try the hints first.

In Lab 1, repair the search and try Alex’s mistyped listing ID in **Shop**.
The handoff proves the repair and prepares Lab 2. In Lab 2, fix the ranking
formula. Try his monitor search in **Shop** before comparing settings and handing
off to Lab 3. Use `uv run python scripts/lab_state.py status` to see where each lab stands.

After deploying your agent in Lab 3, open **Ask Mosaic** and choose **Complete my setup**.
Check the source behind a claim about the chair. Start a new conversation for the 100W
question, then run `uv run python scripts/grade_setup_run.py` to check both saved
answers. Try your own question after the check passes.

After the labs, open **Playground → Use it in your own agent** and choose
**Download the agent skill** to keep the agentic hybrid retrieval skill, or
**Download the SQL and guide** to adapt the search to your own data. For
the source layout, see [the repository map](docs/index.md) and
[the agent guidance](AGENTS.md).
