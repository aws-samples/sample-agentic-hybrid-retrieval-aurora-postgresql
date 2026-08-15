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
    INDEX_PARAMETERS,
    SQL_DEFAULTS,
    Report,
    check_exemptions_complete,
    check_index_agreement,
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
