# Start here · Mosaic

Help Alex find the right products, rank them fairly, and explain a choice
with evidence. Your Aurora database and application are already running.

## Begin in the workshop guide

Keep **Workshop Studio → Lab 1** beside this editor. Follow **Observe the
failure**, capture the result, then investigate before changing code.
Use **Mosaic → Labs** to inspect the search and keep its saved search record.

The terminal below is ready. It opens in this checkout with the workshop
connection settings loaded. You do not need to start a database or server.

## Your route through the code

| Step | Question to investigate | File you will edit |
|---|---|---|
| Retrieve | Where did the missing product leave the candidate path? | [Search functions](db/sql/09_search_functions.sql) |
| Rank | Did the combined order preserve each search method's positions? | [Search functions](db/sql/09_search_functions.sql) |
| Build an agent | Can your Strands agent use SQL tools and answer with sources? | [Agent factory](labs/lab3/agent.py) |

Read the guide's task before editing. Labs 1 and 2 each have one SQL repair.
In Lab 3, complete the Strands agent, run `make deploy-agent`, then ask a product
question and follow up. The guide provides hints and a recovery command.

## Explore Mosaic's source

- **`ui/`** — the Mosaic storefront and lab workbench.
- **`service/`** — the API, agent tools, retrieval and citation checks.
- **`db/`** — SQL, indexes and retrieval configuration.
- **`scripts/`** — lab commands, validators and evaluation utilities.
- **`labs/`** — the Strands agent you build.
- **`.local/lab-1`, `lab-2`, `lab-3`** — your queries and saved experiment records.
- **`skills/`** — the portable hybrid agentic search skill.

Read [AGENTS.md](AGENTS.md) for repository rules, [VOICE.md](VOICE.md) for the
application's writing style, and [CLAUDE.md](CLAUDE.md) for coding-agent guidance.
The Explorer hides caches and build outputs; the source paths match the guide.

## Keep the proof

Labs 1 and 2 ask for one written prediction and one two-sentence explanation in
`learning-notes.md` in your prepared Code Editor: explain the mechanism, not
just the winning card. Bootstrap creates this notes file for each participant.
Complete the guide's validation commands before moving to the next lab.

After completion, download **Hybrid Agentic Search** from Mosaic's Labs
page to carry the workflow and its quality checks into your own agent.
