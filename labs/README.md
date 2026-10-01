# Labs

Open [Mosaic.code-workspace](../Mosaic.code-workspace) for the numbered Explorer
groups **01 — Retrieve**, **02 — Rank & Re-rank**, and **03 — Reason**. They point to the
existing folders below. **Explore Mosaic source** contains the repository root,
where every prepared terminal starts.

Each lab has its own folder. The folder holds the file you edit, a README with
the task, and `solution/` with the reference answer. Your Workshop Studio guide
leads every step; these files are where the fix happens.

| Lab | Folder | You edit | Aurora or Runtime picks up your edit with |
|---|---|---|---|
| 1. Retrieve | [`lab1_retrieve/`](lab1_retrieve/) | `hybrid_search.sql`, two marked blocks | `uv run python scripts/apply_search_functions.py` |
| 2. Rank | [`lab2_rank/`](lab2_rank/) | `rrf_contribution.sql`, one marked block | `uv run python scripts/apply_search_functions.py` |
| 3. Reason | [`lab3_reason/`](lab3_reason/) | `agent.py`, one marked block | `uv run python scripts/deploy_agentcore.py deploy` |

Every lab README follows **Broken → Diagnose → Fix → Prove**. Its collapsed
recovery section links the reference answer; `solution/` folders are hidden from
the default Explorer view. The marked blocks sit between
`LABn_..._START` and `LABn_..._END` comments. When a lab starts, each block holds
a `TODO(Lab n)` note that repeats the guide's contract for the edit.

## Commands, in the order the guides use them

1. `uv run python scripts/lab_state.py status` shows where each lab stands.
2. `uv run python scripts/lab_state.py start --lab N` enters a lab and saves its
   failing request so you can compare before and after.
3. Edit the marked blocks.
4. Apply the SQL (Labs 1 and 2) or deploy the agent (Lab 3). Editing a file does
   not change Aurora or Runtime on its own.
5. Prove it: `uv run python scripts/validate_lab.py --lab N` for Labs 1 and 2,
   or `uv run python scripts/complete_agent.py --run-id <your-run-id>` for Lab 3.

To start one lab over, `uv run python scripts/lab_state.py reset --lab N`
restores its starter. To install the reference answer instead,
`uv run python scripts/lab_state.py solution --lab N` overwrites your edit.

## How the lab SQL is installed

The two lab SQL files install together with the retrieval channels in `db/sql/`.
`db/sql/install.sql` lists the order: the channels, Lab 2's contribution, Lab 1's
hybrid search, then the weighted fusion and evidence search that reuse Lab 2's
function.
