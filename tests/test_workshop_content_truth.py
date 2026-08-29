"""Pin participant-facing claims to the executable three-lab contract."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_reason_lab_teaches_citation_scope_not_authorization():
    contract = json.loads(_read("data/evals/mosaic_labs_missions.json"))
    reason = next(
        mission for mission in contract["missions"] if mission["stage"] == "reason"
    )
    participant_copy = " ".join(
        [
            reason["expected_outcome"],
            reason["participant_edit"]["task"],
            reason["participant_edit"]["broken_state"],
            reason["participant_edit"]["fixed_state"],
            *reason["participant_edit"]["observe_before"],
            *reason["participant_edit"]["observe_after"],
            reason["participant_edit"]["checkpoint_question"],
        ]
    ).casefold()
    curriculum = _read("docs/retrieval-curriculum.md").casefold()

    assert "authorization" not in participant_copy
    assert "authorized" not in participant_copy
    assert "authorization" not in curriculum
    assert "authorized" not in curriculum
    assert "citation scope" in participant_copy
    assert "citation scope" in curriculum
    assert reason["requires_independent_target_searches"] is True
    assert reason["requires_explain_plan"] is True


def test_repo_abstract_promises_focused_repairs_and_inspection():
    abstract = _read("docs/session-abstract.md").casefold()

    assert "restore" in abstract
    assert "repair" in abstract
    assert "inspect" in abstract
    assert "implement every" not in abstract


def test_evaluation_docs_count_twenty_product_cases_plus_one_agent_case():
    plan = _read("docs/evaluation-plan.md")
    normalized_plan = " ".join(plan.split())
    curriculum = _read("docs/retrieval-curriculum.md")

    assert "20 single-request product-retrieval cases" in normalized_plan
    assert "one agent-contract case" in normalized_plan
    assert "all 20 per-query metrics" in normalized_plan
    assert "20-query ranking population" in curriculum


def test_optional_mcp_is_not_labeled_as_a_lab_3_checkpoint():
    index = _read("docs/index.md")

    assert "Lab 3 MCP checkpoint" not in index
    assert "| `mcp-interoperability.md` | Optional" in index


def test_readme_hands_off_the_complete_participant_skill():
    readme = " ".join(_read("README.md").split())

    assert "four-operation HTTP skill surface" in readme
    assert "three typed, catalog-read-only" in readme
    assert "not a standalone retrieval runtime" in readme
    assert "skills/mosaic-hybrid-retrieval/references/adapting.md" in readme
    assert "uv run python scripts/tool_contracts.py --check" in readme


def test_prove_is_an_unnumbered_finale_not_a_fourth_lab():
    curriculum = _read("docs/retrieval-curriculum.md")

    assert "Prove (unnumbered finale)" in curriculum
    assert "not a fourth lab" in curriculum


def test_hnsw_status_separates_serving_from_benchmark_certification():
    status = _read("docs/implementation-status.md")

    assert "The serving HNSW path is implemented." in status
    assert "HNSW retrieval itself is not deferred" in status
