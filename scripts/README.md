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
| `uv run python scripts/lab_state.py reset --lab N` | Restore one lab's starter |
| `uv run python scripts/lab_state.py solution --lab N` | Install the reference answer, overwriting your edit |
| `uv run python scripts/apply_search_functions.py` | Install your Lab 1 and Lab 2 SQL in Aurora |
| `uv run python scripts/validate_lab.py --lab N` | Prove a Lab 1 or Lab 2 repair |
| `uv run python scripts/deploy_agentcore.py tools\|deploy\|verify` | List the SQL tools, deploy your Lab 3 agent, recheck the deployment |
| `uv run python scripts/complete_agent.py --run-id <your-run-id>` | Check your saved Lab 3 run |

The guides also use `lab_exercise.py`, `lab_terminal.py`, `flex_exercise.py`
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
| [`media/`](media/) | Product photography manifests and image installation |

Run them from the repository root, for example
`uv run python scripts/checks/config_tripwire.py`. The root `Makefile` wraps the
ones maintainers run routinely.
