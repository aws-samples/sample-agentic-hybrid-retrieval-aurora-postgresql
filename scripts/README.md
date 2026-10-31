# Scripts

The top of this folder holds what participants run, and the helpers those
commands need. Everything else is maintainer tooling, grouped by job.

## Participant commands

Every lab guide shows these exact commands; `service/participant_commands.py`
holds the same strings for every message the app prints.

| Command | What it does |
|---|---|
| `uv run python scripts/lab_state.py status` | Show where each lab stands |
| `uv run python scripts/lab_state.py start --lab N` | Enter a lab and save its failing request |
| `uv run python scripts/lab_state.py advance --lab 1` | Prove Lab 1 live, save its evidence and prepare Lab 2; your edits are kept |
| `uv run python scripts/lab_state.py advance --lab 2` | Prove Lab 2 live, save its evidence and install the Retrieval agent's starting code for Lab 3 |
| `uv run python scripts/lab_state.py reset --lab N` | Restore one lab's starting code |
| `uv run python scripts/lab_state.py apply-solution --lab N` | Install the reference answer, overwriting your edit |
| `uv run python scripts/lab_state.py finish --lab N` | Finish a lab, and any earlier lab not handed off, with the reference answer, its checks and its hand-off |
| `uv run python scripts/lab_state.py skip-to --lab N` | Finish the earlier labs the same way and stop at lab N's start |
| `uv run python scripts/diff.py` | Name the lines of your lab files that differ from the reference answer, inside and outside the markers, without printing the answer; `--answer` adds it; changes nothing |
| `uv run python scripts/apply_search_functions.py` | Install your Lab 1 and Lab 2 SQL in Aurora |
| `uv run python scripts/lab_state.py validate --lab N --database-url "$DATABASE_URL"` | Check the saved source and the SQL Aurora last applied (Labs 1 and 2) |
| `uv run python scripts/lab_request.py send --lab N --phase after` | Repeat the saved request against your repaired state and print Before and After |
| `uv run python scripts/prove_lab.py --lab N` | Prove a Lab 1 or Lab 2 repair |
| `uv run python scripts/deploy_agentcore.py tools\|deploy\|verify\|resources` | List the SQL tools, deploy your Lab 3 agent, recheck the deployment, show the runtimes, Gateway and Memory |
| `uv run python scripts/ask_agent.py "QUESTION"` | Ask your deployed agent and read its answer of record: trace, citations, outcome, decline reason |
| `uv run python scripts/check_claim.py PRODUCT_ID "SENTENCE [1]"` | Run a sentence through the agent's answer checks with the product's listing as [1]: a stated figure must be in the record |
| `uv run python scripts/grade_setup_run.py [--run-id <run-id>]` | Check your newest Lab 3 setup run, or the run named |

The guides also use `lab_exercise.py`, `lab_request.py`, `hnsw_exercise.py`
and `python -m scripts.check_builder_tool` for optional exercises. The other
files at this level are helpers those commands import, except
`prepare_real_catalog.py` and `embed_real_catalog.py`: guides published before
the scripts moved into `catalog/` link those paths, so each is a one-line
pointer to its new location.

## Maintainer tooling

| Folder | What it holds |
|---|---|
| [`catalog/`](catalog/) | Building, verifying and caching the real product catalog |
| [`evals/`](evals/) | The canonical scorecard, the stage ablation and held-out relevance judgments |
| [`bench/`](bench/) | HNSW and scale benchmarks against the served catalog |
| [`checks/`](checks/) | Release gates: retrieval configuration, tool contracts, the lab contract, model access |

Run them from the repository root, for example
`uv run python scripts/checks/config_tripwire.py`. The root `Makefile` wraps the
ones maintainers run routinely.
