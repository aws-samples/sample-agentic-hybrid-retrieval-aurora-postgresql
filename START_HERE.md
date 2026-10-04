# Start here · Mosaic

Help Alex find the right products, rank them fairly, and explain a choice
with evidence. Your Aurora database and application are already running.

## Begin in the workshop guide

Keep **Workshop Studio → Lab 1** beside this editor. Follow **Observe the
failure**, capture the result, then investigate before changing code.
Use **Mosaic → Playground** to inspect the search and keep its saved search record.

The terminal below is ready. It opens in this checkout with the workshop
connection settings loaded. You do not need to start a database or server.

## Your route through the code

The Explorer groups your work as **01 — Retrieve**, **02 — Rank & Re-rank**, and
**03 — Reason**. Each group opens the real lab directory: its README and the
file you edit. **04 — Explore Mosaic source** contains the application source and
[learning-notes.md](learning-notes.md); maintainer-only files are hidden. Every prepared terminal starts at the
repository root, including when a lab file is selected.

If an older editor link shows only the repository folder, choose **File → Open
Workspace from File…** and open `Mosaic.code-workspace` in this checkout. The
same files and saved work appear in the numbered view.

| Step | Question to investigate | File you will edit |
|---|---|---|
| 01 — Retrieve | Where did the missing product leave the candidate path? | [Hybrid search](labs/lab1_retrieve/hybrid_search.sql) |
| 02 — Rank & Re-rank | Did the combined order preserve each search method's positions? | [Rank contribution](labs/lab2_rank/rrf_contribution.sql) |
| 03 — Reason | Can your Strands agent use SQL tools and answer with sources? | [Agent factory](labs/lab3_reason/agent.py) |

Read the guide's task before editing. Each lab's folder has a README with the
task and commands; when a lab starts, its marked blocks hold a `TODO(Lab n)`
note. Labs 1 and 2 each have one SQL repair.
In Lab 3, complete the Strands agent, deploy it with
`uv run python scripts/deploy_agentcore.py deploy`, then ask a product
question and follow up. The guide provides hints and a recovery command.

## Explore Mosaic's source

- **`ui/`** — the Mosaic storefront and lab workbench.
- **`service/`** — the API, agent tools, retrieval and citation checks.
- **`labs/`** — one folder per lab: the file you edit, its task and a
  `solution/` copy of the reference answer, linked from the README’s recovery
  section and hidden from the default Explorer view.
- **`db/`** — the rest of the SQL, numbered in install order, and retrieval
  configuration.
- **`scripts/`** — the lab commands at the top; maintainer tooling in
  `catalog/`, `evals/`, `bench/` and `checks/`.
- **`.local/lab-1`, `lab-2`, `lab-3`** — your queries and saved experiment records.
- **`skills/`** — the portable hybrid agentic search skill.

Read [AGENTS.md](AGENTS.md) for repository rules, [VOICE.md](VOICE.md) for the
application's writing style, and [CLAUDE.md](CLAUDE.md) for coding-agent guidance.
The Explorer hides caches, build outputs, solution folders and maintainer-only
files such as tests and CI; the source paths match the guide. Opening a numbered group does not create another copy of a file.

## Keep the proof

Labs 1 and 2 ask for one written prediction and one two-sentence explanation in
`learning-notes.md` in your prepared Code Editor: explain the mechanism, not
just the winning card. Bootstrap creates this notes file for each participant.
Complete the guide's validation commands before moving to the next lab.

After completion, download **Hybrid Agentic Search** from Mosaic's Playground
page to carry the workflow and its quality checks into your own agent.

The Playground has four phases across the three labs: **Retrieve → Rank → Re-rank → Reason**. Lab 2a repairs Rank; Lab 2b inspects Re-rank and compares three measured settings on judged queries within the same ten-minute lab. Lab 3 brings the headphones, monitor and chair together in **Complete my room**. Save that original three-product run for completion.
