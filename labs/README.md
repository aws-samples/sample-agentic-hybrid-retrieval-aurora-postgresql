# Labs

Follow Workshop Studio in order. [Mosaic.code-workspace](../Mosaic.code-workspace)
opens **01 - Retrieve**, **02 - Rank and re-rank**, **03 - Reason** and
**04 - Explore Mosaic source**. All terminals start at the repository root.

| Lab | Edit | Apply or deploy |
|---|---|---|
| [1 · Retrieve](lab1_retrieve/) | `hybrid_search.sql`: `LAB1_CHANNEL` block | `uv run python scripts/apply_search_functions.py` |
| [2 · Rank and re-rank](lab2_rank/) | `rrf_contribution.sql`: `LAB2_RRF_FORMULA` block | `uv run python scripts/apply_search_functions.py` |
| [3 · Reason](lab3_reason/) | `agent.py`: `LAB3_AGENT` block | `uv run python scripts/deploy_agentcore.py deploy` |

Each README follows **Broken → Diagnose → Fix → Prove**. Start with
`uv run python scripts/lab_state.py start --lab N`, keep the saved request,
and predict the cause before editing. Saving a file
does not update Aurora or Runtime. Complete the guide's proof before moving on.

<details>
<summary>🛠️ Recovery</summary>

`uv run python scripts/lab_state.py reset --lab N` discards that lab's edits
and restores its starter. The guide's Hint 4 applies the reference answer;
the lab README links its hidden `solution/` copy. Recovery still needs proof.

</details>
