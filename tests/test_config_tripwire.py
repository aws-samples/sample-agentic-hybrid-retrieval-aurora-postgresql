"""The tripwire must fail on the drift it exists to catch.

House bar: a green check is not evidence on its own. These are the permanent
falsifier fixtures — the violations proven red by hand during Unit C, kept as
test cases so the check is re-proven on every run rather than once at birth.

Each test builds a throwaway repository tree, so nothing here can touch the real
files. `scan_declarations` and the agreement checks take a `repo` argument for
exactly this reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.config_tripwire import (
    ALLOWED_LINE,
    DECLARATION,
    INDEX_PARAMETERS,
    SQL_DEFAULTS,
    Report,
    check_exemptions_complete,
    check_index_agreement,
    check_model_agreement,
    check_model_exemptions_complete,
    check_sql_agreement,
    scan_declarations,
)
from scripts.retrieval_profile import RETRIEVAL_YAML

REPO = Path(__file__).resolve().parents[1]

SIGNATURE = """\\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(
    q text,
    rrf_k integer DEFAULT {rrf_k},
    fts_limit integer DEFAULT {fts_limit}
)
RETURNS TABLE (product_id bigint)
LANGUAGE sql
AS $$ SELECT 1 $$;
"""

INDEX_DDL = """\\set ON_ERROR_STOP on

CREATE INDEX CONCURRENTLY IF NOT EXISTS product_document_embedding_hnsw_cosine_idx
    ON mosaic_search.product_document
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = {ef_construction})
    WHERE embedding IS NOT NULL;
"""


def rules(report: Report) -> set[str]:
    """The rule ids that fired, e.g. {"C1", "C1b"}."""
    return {failure.split()[0] for failure in report.failures}


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal tree with the real yaml and a clean SQL file."""
    (tmp_path / "service").mkdir()
    (tmp_path / "db" / "sql").mkdir(parents=True)
    (tmp_path / "db" / "config").mkdir(parents=True)
    (tmp_path / "db" / "config" / "retrieval.yaml").write_text(
        RETRIEVAL_YAML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "db" / "sql" / "09_search_functions.sql").write_text(
        SIGNATURE.format(rrf_k=60, fts_limit=120), encoding="utf-8"
    )
    (tmp_path / "db" / "sql" / "08_indexes_concurrent.sql").write_text(
        INDEX_DDL.format(ef_construction=200), encoding="utf-8"
    )
    return tmp_path


def test_the_real_repository_is_clean():
    """The live tree must satisfy both rules; this is the regression guard."""
    report = Report()
    scan_declarations(report)
    check_sql_agreement(report)
    check_index_agreement(report)
    assert report.failures == [], report.failures


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("service/second_copy.py", "fts_limit = 200\n"),
        ("service/second_copy.py", "rrf_k = 42\n"),
        ("service/second_copy.py", "trigram_limit=99\n"),
    ],
)
def test_a_second_python_declaration_is_caught(fake_repo, filename, body):
    (fake_repo / filename).write_text(body, encoding="utf-8")
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert "C1" in rules(report), f"{body!r} was not caught"


def test_a_typescript_fallback_is_caught(fake_repo):
    """`?? 60` decides what a participant sees, so it is a declaration."""
    (fake_repo / "ui" / "src").mkdir(parents=True)
    (fake_repo / "ui" / "src" / "Panel.tsx").write_text(
        "const k = diagnostics?.rrf_k ?? 60;\n", encoding="utf-8"
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert "C1" in rules(report)


def test_an_rrf_literal_inside_an_expression_is_caught(fake_repo):
    path = fake_repo / "db" / "sql" / "evidence.sql"
    path.write_text(
        "SELECT 1.0 / (60 + evidence_rank) AS fused_score;\n",
        encoding="utf-8",
    )

    report = Report()
    scan_declarations(report, repo=fake_repo)

    assert "C1" in rules(report)
    assert any("hardcodes k=60" in failure for failure in report.failures)


def test_a_resurrected_workshop_json_is_caught(fake_repo):
    """Unit C deleted this file; recreating it must fail rather than be ignored."""
    (fake_repo / "config").mkdir()
    (fake_repo / "config" / "workshop.json").write_text(
        json.dumps({"retrieval": {"lexical_candidate_limit": 100, "rrf_k": 60}}),
        encoding="utf-8",
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert "C1" in rules(report)


def test_environment_reads_are_not_declarations(fake_repo):
    """The override path must stay usable, or the rule blocks its own escape hatch."""
    (fake_repo / "service" / "reader.py").write_text(
        'fts_limit = os.getenv("FTS_CANDIDATE_LIMIT")\n', encoding="utf-8"
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert not report.failures, report.failures


def test_pydantic_bounds_are_not_declarations(fake_repo):
    """A bound is a range, not a value; forbidding it would forbid validation."""
    (fake_repo / "service" / "bounded.py").write_text(
        "fts_limit: int = Field(default_factory=_yaml_default('fts_limit'), "
        "ge=1, le=1000)\n",
        encoding="utf-8",
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert not report.failures, report.failures


def test_a_comment_explaining_a_number_is_not_a_declaration(fake_repo):
    """Comments are where these numbers get explained. Explaining is not declaring."""
    (fake_repo / "service" / "prose.py").write_text(
        "# The live default is fts_limit = 120, set in the yaml.\n", encoding="utf-8"
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert not report.failures, report.failures


def test_the_yaml_itself_is_never_a_violation(fake_repo):
    """The single source declaring its own numbers is the entire point."""
    report = Report()
    scan_declarations(report, repo=fake_repo)
    assert not any("retrieval.yaml" in f for f in report.failures), report.failures


@pytest.mark.parametrize("drifted", [90, 121, 0])
def test_a_drifted_sql_default_is_caught(fake_repo, drifted):
    """The exemption is a monitored seam: exempt from declaring, never from agreeing."""
    (fake_repo / "db" / "sql" / "09_search_functions.sql").write_text(
        SIGNATURE.format(rrf_k=60, fts_limit=drifted), encoding="utf-8"
    )
    report = Report()
    check_sql_agreement(report, repo=fake_repo)
    assert "C1b" in rules(report), f"SQL default {drifted} did not fail agreement"


def test_a_drifted_index_parameter_is_caught(fake_repo):
    """An index built off-profile makes measured recall untraceable to config."""
    (fake_repo / "db" / "sql" / "08_indexes_concurrent.sql").write_text(
        INDEX_DDL.format(ef_construction=400), encoding="utf-8"
    )
    report = Report()
    check_index_agreement(report, repo=fake_repo)
    assert "C1b" in rules(report)


def test_a_stale_exemption_entry_is_caught(fake_repo):
    """A removed default must not read as agreement."""
    (fake_repo / "db" / "sql" / "09_search_functions.sql").write_text(
        "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(q text)\n"
        "RETURNS TABLE (product_id bigint) LANGUAGE sql AS $$ SELECT 1 $$;\n",
        encoding="utf-8",
    )
    report = Report()
    check_sql_agreement(report, repo=fake_repo)
    assert "C1b" in rules(report)


def test_an_unpinned_sql_default_is_caught(fake_repo):
    """Rule 3: rule 1 cannot see `name type DEFAULT value` — it has no `=` or `:`.

    Unit D added 13 such defaults, three of them fusion weights, and the tripwire
    stayed green with none of them pinned. A monitored seam that only monitors
    what someone remembered to list is not monitored.
    """
    (fake_repo / "db" / "sql" / "09_search_functions.sql").write_text(
        "CREATE OR REPLACE FUNCTION mosaic_search.invented(\n"
        "    q text,\n"
        "    weight_lexical real DEFAULT 0.30\n"
        ")\nRETURNS TABLE (product_id bigint) LANGUAGE sql AS $$ SELECT 1 $$;\n",
        encoding="utf-8",
    )
    report = Report()
    check_exemptions_complete(report, repo=fake_repo)
    assert "C1c" in rules(report)


def test_a_pinned_sql_default_is_not_reported_twice(fake_repo):
    """The completeness rule must not fire on defaults rule 2 already checks."""
    report = Report()
    check_exemptions_complete(report, repo=fake_repo)
    assert not report.failures, report.failures


def test_the_real_repository_pins_every_sql_default():
    """Regression guard: adding a function default without pinning it fails here."""
    report = Report()
    check_exemptions_complete(report)
    assert report.failures == [], report.failures


def test_every_exemption_names_a_yaml_field_or_states_a_reason():
    """An unexplained exemption is the blind spot this design exists to avoid."""
    for entry in SQL_DEFAULTS + INDEX_PARAMETERS:
        if entry.profile_field is None:
            assert entry.reason.strip(), f"{entry.parameter} is exempt with no reason"
            assert len(entry.reason) > 40, f"{entry.parameter} reason is not specific"


def test_every_failure_message_names_the_value_and_a_fix(fake_repo):
    """House standard, same as the mission gate."""
    (fake_repo / "service" / "second_copy.py").write_text(
        "fts_limit = 200\n", encoding="utf-8"
    )
    (fake_repo / "db" / "sql" / "09_search_functions.sql").write_text(
        SIGNATURE.format(rrf_k=7, fts_limit=90), encoding="utf-8"
    )
    report = Report()
    scan_declarations(report, repo=fake_repo)
    check_sql_agreement(report, repo=fake_repo)
    assert report.failures
    for failure in report.failures:
        assert "found " in failure, failure
        assert "fix: " in failure, failure


# Every field MODEL_DEFAULTS pins, at the values the yaml currently yields. The
# values are written out rather than read from the profile on purpose: a fixture
# that derived its expectations from the file under test could not fail, which is
# the self-reference trap these gates exist to avoid. If the yaml moves, this
# fixture goes stale and says so.
MODEL = '''"""Typed application contracts."""

from pydantic import BaseModel, Field


class RetrievalProfile(BaseModel):
    fts_limit: int = Field(default={fts_limit}, ge=1, le=1000)
    trigram_limit: int = Field(default=80, ge=1, le=1000)
    semantic_limit: int = Field(default=150, ge=1, le=1000)
    fused_limit: int = Field(default=50, ge=1, le=250)
    result_limit: int = Field(default=12, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1)
    ef_search: int = Field(default=100, ge=1, le=1000)
    max_scan_tuples: int = Field(default=20000, ge=1)
    scan_mem_multiplier: float = Field(default={scan_mem_multiplier}, ge=1)
'''


@pytest.fixture
def fake_model_repo(fake_repo: Path) -> Path:
    """`fake_repo` plus a db/models/python tree holding a clean contract file."""
    (fake_repo / "db" / "models" / "python").mkdir(parents=True)
    (fake_repo / "db" / "models" / "python" / "mosaic_models.py").write_text(
        MODEL.format(fts_limit=120, scan_mem_multiplier=2), encoding="utf-8"
    )
    return fake_repo


def test_the_pydantic_field_shape_is_invisible_to_rule_1():
    """Why rule C1d has to exist rather than just widening SCAN_ROOTS.

    For `scan_mem_multiplier: float = Field(default=1, ge=1)` the DECLARATION
    pattern does not match — the token after `:` is `float`, not a number — and
    ALLOWED_LINE matches anyway because of `ge=1`. The shape is invisible twice
    over, so adding `db/models` to SCAN_ROOTS alone leaves the check green.
    """
    line = "    scan_mem_multiplier: float = Field(default=1, ge=1)\n"

    assert DECLARATION.search(line) is None
    assert ALLOWED_LINE.search(line) is not None


def test_model_defaults_agreeing_with_the_yaml_pass(fake_model_repo: Path):
    report = Report()

    check_model_agreement(report, repo=fake_model_repo)

    assert report.failures == []


def test_a_disagreeing_model_default_fires_c1d(fake_model_repo: Path):
    (fake_model_repo / "db" / "models" / "python" / "mosaic_models.py").write_text(
        MODEL.format(fts_limit=999, scan_mem_multiplier=2), encoding="utf-8"
    )
    report = Report()

    check_model_agreement(report, repo=fake_model_repo)

    assert rules(report) == {"C1d"}
    assert "999" in report.failures[0]
    assert "fix:" in report.failures[0]


def test_a_missing_model_default_fires_c1d(fake_model_repo: Path):
    """A stale exemption list must fail loudly rather than skip silently."""
    (fake_model_repo / "db" / "models" / "python" / "mosaic_models.py").write_text(
        '"""Contracts."""\n', encoding="utf-8"
    )
    report = Report()

    check_model_agreement(report, repo=fake_model_repo)

    assert rules(report) == {"C1d"}


def test_an_unenumerated_model_default_fires_c1e(fake_model_repo: Path):
    """`ef_construction` holds a retrieval number and is not in MODEL_DEFAULTS.

    Adding a tenth number to the packaged contract must fail until it is pinned,
    because C1d only checks what someone remembered to list.
    """
    path = fake_model_repo / "db" / "models" / "python" / "mosaic_models.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "    ef_construction: int = Field(default=200, ge=4)\n",
        encoding="utf-8",
    )
    report = Report()

    check_model_exemptions_complete(report, repo=fake_model_repo)

    assert rules(report) == {"C1e"}
    assert "ef_construction" in report.failures[0]


def test_a_non_retrieval_model_default_is_not_required_to_be_enumerated(
    fake_model_repo: Path,
):
    path = fake_model_repo / "db" / "models" / "python" / "mosaic_models.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "    weight_g: int = Field(default=42)\n",
        encoding="utf-8",
    )
    report = Report()

    check_model_exemptions_complete(report, repo=fake_model_repo)

    assert report.failures == []


def test_the_real_model_contract_agrees_with_the_yaml():
    report = Report()

    check_model_agreement(report)
    check_model_exemptions_complete(report)

    assert report.failures == [], report.failures
