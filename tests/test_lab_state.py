from pathlib import Path
from shutil import copy2

import pytest

from scripts.lab_state import (
    LABS,
    REPO,
    lab_is_solved,
    set_isolated_lab_state,
    set_lab_state,
)

PARTICIPANT_CTE = """, trigram AS (
    SELECT product_id, trigram_score, trigram_rank
    FROM mosaic_search.search_trigram(q, f, trigram_limit, trigram_threshold)
)"""
PARTICIPANT_CHANNEL = """    UNION ALL
    SELECT product_id, 'trigram'::text AS channel, trigram_rank AS source_rank,
           trigram_score AS raw_score,
           mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k)
               AS contribution
    FROM trigram"""


@pytest.fixture
def lab_repo(tmp_path: Path) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


def _lab_bytes(repo: Path) -> dict[str, bytes]:
    return {
        relative_path: (repo / relative_path).read_bytes()
        for relative_path in {definition[0] for definition in LABS.values()}
    }


def participant_lab1(repo: Path) -> str:
    from scripts.lab_state import _replace_block

    path = repo / LABS[1][0]
    source = path.read_text()
    for (start, end, _, _), replacement in zip(
        LABS[1][1], (PARTICIPANT_CTE, PARTICIPANT_CHANNEL), strict=True
    ):
        source = _replace_block(source, start, end, replacement)
    path.write_text(source)
    return source


def test_lab1_accepts_the_participant_repair_that_passed_live_retrieval(lab_repo):
    participant_lab1(lab_repo)
    assert lab_is_solved(1, repo=lab_repo)


def test_applied_lab1_accepts_a_different_cte_name(lab_repo, monkeypatch):
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    source = participant_lab1(lab_repo)
    definition = source.split(
        "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(", 1
    )[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    connection.execute.return_value.fetchone.return_value = {
        "definition": definition.replace("mosaic_search.", "mosaic_live_search.")
    }
    assert validate_database(1, connection).state == "applied"


def test_applied_lab1_does_not_accept_disconnected_name_mentions():
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "definition": "-- search_trigram is missing\nSELECT product_id FROM typo"
    }
    assert validate_database(1, connection).state == "stale"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("(q, f, trigram_limit", "(q, '{}'::jsonb, trigram_limit"),
        ("trigram_limit, trigram_threshold)", "trigram_limit, 0.0)"),
        ("UNION ALL", "UNION"),
        ("'trigram'::text", "'vector'::text"),
        ("trigram_rank AS source_rank", "1 AS source_rank"),
        ("trigram_score AS raw_score", "trigram_rank AS raw_score"),
        ("(trigram_rank, rrf_k)", "(1, rrf_k)"),
        ("FROM trigram", "FROM semantic"),
    ],
)
def test_lab1_contract_rejects_changed_data_flow_and_restores(lab_repo, old, new):
    participant_lab1(lab_repo)
    path = lab_repo / LABS[1][0]
    original = path.read_bytes()
    assert old in original.decode()
    path.write_text(original.decode().replace(old, new))
    assert not lab_is_solved(1, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(1, repo=lab_repo)


def test_lab1_contract_ignores_local_names_comments_and_projection_order(lab_repo):
    source = participant_lab1(lab_repo)
    source = source.replace("trigram AS (", "recovered AS (")
    source = source.replace("FROM trigram", "FROM recovered")
    source = source.replace(
        "SELECT product_id, trigram_score, trigram_rank",
        "select trigram_rank, /* still named */ product_id, trigram_score",
    )
    source = source.replace("AS raw_score", "AS ignored_union_alias -- output name\n")
    (lab_repo / LABS[1][0]).write_text(source)
    assert lab_is_solved(1, repo=lab_repo)


@pytest.mark.parametrize("lab", [1, 2, 3])
def test_source_gate_ignores_layout_but_preserves_the_repair(lab_repo, lab):
    from scripts.lab_state import _replace_block

    set_lab_state(lab, solved=True, repo=lab_repo)
    path = lab_repo / LABS[lab][0]
    original = path.read_bytes()
    source = original.decode()
    for start, end, fixed, _ in LABS[lab][1]:
        formatted = (
            fixed.replace("tools=tools,", "tools = tools,")
            if lab == 3
            else " ".join(fixed.split())
        )
        source = _replace_block(source, start, end, formatted)
    assert source.encode() != original
    path.write_text(source)
    assert lab_is_solved(lab, repo=lab_repo)
    set_lab_state(lab, solved=False, repo=lab_repo)
    assert not lab_is_solved(lab, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(lab, repo=lab_repo)


def test_source_gate_preserves_string_contents(lab_repo):
    set_lab_state(1, solved=True, repo=lab_repo)
    path = lab_repo / LABS[1][0]
    path.write_text(path.read_text().replace("'trigram'", "'tri gram'"))
    assert not lab_is_solved(1, repo=lab_repo)


@pytest.mark.parametrize("later_lab", [2, 3])
def test_a_later_reset_keeps_the_participants_valid_lab1_repair(
    lab_repo: Path, later_lab: int
) -> None:
    participant_lab1(lab_repo)

    set_isolated_lab_state(later_lab, repo=lab_repo)

    source = (lab_repo / LABS[1][0]).read_text()
    assert PARTICIPANT_CTE in source
    assert PARTICIPANT_CHANNEL in source
    assert lab_is_solved(1, repo=lab_repo)
    assert not lab_is_solved(later_lab, repo=lab_repo)


@pytest.mark.parametrize(
    "formula",
    [
        "SELECT 1.0 / (rrf_k + source_rank)",
        "select 1::float8 / (source_rank + rrf_k);",
        "SELECT 1 / (rrf_k::double precision + /* keep ranks */ source_rank)",
    ],
)
def test_lab3_reset_preserves_participant_lab2_formula(lab_repo, formula):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[2][0]
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, formula))
    original = path.read_bytes()
    assert lab_is_solved(2, repo=lab_repo)

    changed = set_isolated_lab_state(3, repo=lab_repo)

    assert lab_repo / LABS[3][0] in changed
    assert not lab_is_solved(3, repo=lab_repo)
    assert path.read_bytes() == original
    assert lab_is_solved(2, repo=lab_repo)


@pytest.mark.parametrize(
    "formula",
    [
        "SELECT 1.0 / (rrf_k + 1)",
        "SELECT 1.0 / (source_rank + source_rank)",
        "SELECT 1 / (rrf_k + source_rank)",
        "SELECT 1.0 / (rrf_k + source_rank) + 1",
        "SELECT 1.0 / (rrf_k + source_rank); SELECT 1",
    ],
)
def test_lab2_contract_rejects_wrong_formula_and_restores(lab_repo, formula):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[2][0]
    original = path.read_bytes()
    assert lab_is_solved(2, repo=lab_repo)
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, formula))
    assert not lab_is_solved(2, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(2, repo=lab_repo)


@pytest.mark.parametrize("lab", sorted(LABS))
def test_reset_and_solution_are_idempotent(lab_repo: Path, lab: int) -> None:
    set_isolated_lab_state(lab, repo=lab_repo)
    first_reset = _lab_bytes(lab_repo)
    set_isolated_lab_state(lab, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_reset
    assert not lab_is_solved(lab, repo=lab_repo)
    assert all(
        lab_is_solved(candidate, repo=lab_repo)
        for candidate in LABS
        if candidate != lab
    )

    set_lab_state(lab, solved=True, repo=lab_repo)
    first_solution = _lab_bytes(lab_repo)
    set_lab_state(lab, solved=True, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_solution
    assert all(lab_is_solved(candidate, repo=lab_repo) for candidate in LABS)


@pytest.mark.parametrize(
    "identity",
    [
        {
            "name": "unrelated",
            "aurora": "18.3.0",
            "catalog": "mosaic_search.product_document",
        },
        {"name": "mosaic_catalog", "aurora": "18.3.0", "catalog": None},
        {
            "name": "mosaic_catalog",
            "aurora": None,
            "catalog": "mosaic_search.product_document",
        },
    ],
)
def test_reset_guard_rejects_wrong_environment(monkeypatch, identity):
    from unittest.mock import MagicMock

    from scripts.lab_state import assert_reset_database

    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = identity
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: connection)
    monkeypatch.delenv("MOSAIC_WORKSHOP_DATABASE", raising=False)
    with pytest.raises(SystemExit, match="Lab reset rule"):
        assert_reset_database("test-only")


def test_reset_guard_accepts_named_aurora_and_rejects_missing_dsn(monkeypatch):
    from unittest.mock import MagicMock

    from scripts.lab_state import assert_reset_database

    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = {
        "name": "named_workshop",
        "aurora": "18.3.0",
        "catalog": "mosaic_search.product_document",
    }
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: connection)
    monkeypatch.setenv("MOSAIC_WORKSHOP_DATABASE", "named_workshop")
    assert_reset_database("test-only")
    with pytest.raises(SystemExit, match="DATABASE_URL is missing"):
        assert_reset_database(None)


def test_reset_checks_identity_before_editing_files(monkeypatch):
    from scripts import lab_state

    monkeypatch.setattr("sys.argv", ["lab_state.py", "reset", "--lab", "1"])

    def refuse(_):
        raise SystemExit("wrong database")

    monkeypatch.setattr(lab_state, "assert_reset_database", refuse)
    monkeypatch.setattr(
        lab_state,
        "set_isolated_lab_state",
        lambda *_: pytest.fail("edited before identity check"),
    )
    with pytest.raises(SystemExit, match="wrong database"):
        lab_state.main()


@pytest.mark.parametrize("lab", [1, 2])
def test_applied_state_reads_the_catalog_served_by_the_api(monkeypatch, lab):
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database
    from scripts.retrieval_profile import load_profile

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    k = load_profile().rrf_k
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "definition": (REPO / LABS[1][0])
        .read_text()
        .replace("mosaic_search.", "mosaic_live_search."),
        "first_contribution": 1 / (k + 1),
        "second_contribution": 1 / (k + 2),
    }
    assert validate_database(lab, connection).state == "applied"
    statement = connection.execute.call_args.args[0]
    assert "mosaic_live_search." in statement
    assert "mosaic_search." not in statement


PARTICIPANT_LAB3 = """    prompt = instructions + "\\nKeep the answer concise."
    result = Agent(model=model, tools=tools, system_prompt=prompt, hooks=hooks)
    return result"""


def test_lab3_accepts_extra_instructions_and_local_variable_names(lab_repo):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    start, end, _, _ = LABS[3][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, PARTICIPANT_LAB3))
    assert lab_is_solved(3, repo=lab_repo)


@pytest.mark.parametrize(
    "body",
    [
        "    pass",
        "    raise NotImplementedError()",
        "    return {}",
        "    return Agent(model=model, tools=[], system_prompt=instructions, hooks=hooks)",
        "    return Agent(model=None, tools=tools, system_prompt=instructions, hooks=hooks)",
        "    return Agent(model=model, tools=tools, system_prompt='Invent products', hooks=hooks)",
        "    return Agent(model=model, tools=tools, system_prompt=instructions, hooks=[])",
        "    raise SystemExit(0)",
    ],
)
def test_lab3_rejects_missing_agent_parts_and_accepts_byte_identical_restore(
    lab_repo, body
):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    original = path.read_bytes()
    start, end, _, _ = LABS[3][1][0]
    path.write_text(_replace_block(original.decode(), start, end, body))
    assert not lab_is_solved(3, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(3, repo=lab_repo)


def test_registration_probe_calls_the_production_function_with_nonempty_cases():
    from scripts.evidence_registration_probe import registration_matches_contract
    from service.agent_tools import register_evidence

    calls = []

    def observed(state, product_id, evidence):
        calls.append((product_id, len(evidence)))
        register_evidence(state, product_id, evidence)

    assert registration_matches_contract(observed)
    assert calls == [(101, 2), (202, 1), (101, 2), (101, 1), (101, 0)]


def test_lab3_probe_does_not_import_module_startup_code(lab_repo):
    path = lab_repo / LABS[3][0]
    path.write_text(path.read_text() + '\nraise RuntimeError("unrelated startup")\n')
    assert lab_is_solved(3, repo=lab_repo)


def test_lab3_probe_bounds_a_nonterminating_edit(lab_repo):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    start, end, _, _ = LABS[3][1][0]
    path.write_text(
        _replace_block(path.read_text(), start, end, "    while True:\n        pass")
    )
    assert not lab_is_solved(3, repo=lab_repo)
