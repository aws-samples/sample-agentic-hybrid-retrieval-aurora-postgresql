"""Historical Make commands must not load fixtures during real-catalog setup."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_TARGETS = (
    "generate",
    "prepare",
    "media-map",
    "reviews",
    "db-prepare-mosaic",
    "db-load-mosaic",
    "db-load-cohort",
    "db-load-evidence",
    "db-embed",
    "db-fetch-embeddings",
    "db-export-embeddings",
    "db-import-embeddings",
    "db-seed-corpus-lexeme",
)


@pytest.fixture
def run_make(tmp_path):
    makefile = tmp_path / "Makefile"
    makefile.write_bytes((ROOT / "Makefile").read_bytes())
    (tmp_path / "db/sql").mkdir(parents=True)
    witness = tmp_path / "commands"
    stub = tmp_path / "python"
    stub.write_text(
        '#!/bin/sh\n[ "$1" = -c ] && exit 0\n'
        'printf "%s %s\\n" "$0" "$*" >> "$WITNESS"\n'
    )
    stub.chmod(0o755)
    for command in ("psql", "aws"):
        (tmp_path / command).symlink_to(stub)

    def run(target, *, allow="", dataset="", remove_guard=False):
        if remove_guard:
            makefile.write_text(
                makefile.read_text().replace(
                    "$(HISTORICAL_CATALOG_TARGETS): check-historical-catalog",
                    "$(HISTORICAL_CATALOG_TARGETS):",
                )
            )
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DATABASE_URL": "postgresql://unused.invalid/test",
            "WITNESS": str(witness),
        }
        result = subprocess.run(
            [
                "make",
                "--no-print-directory",
                target,
                f"PYTHON={stub}",
                f"ALLOW_HISTORICAL_CATALOG={allow}",
                f"MOSAIC_CATALOG_DATASET={dataset}",
                "EMBEDDING_CACHE_URI=s3://unused-test-prefix/cache",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        commands = witness.read_text() if witness.exists() else ""
        return result, commands

    return run


@pytest.mark.parametrize("target", HISTORICAL_TARGETS)
def test_historical_commands_require_explicit_opt_in(run_make, target):
    result, commands = run_make(target)
    assert result.returncode != 0
    assert "Historical catalog disabled" in result.stdout
    assert "ALLOW_HISTORICAL_CATALOG=1" in result.stdout
    assert not commands


@pytest.mark.parametrize("target", HISTORICAL_TARGETS)
def test_real_catalog_selection_rejects_historical_commands(run_make, target):
    result, commands = run_make(target, allow="1", dataset="real-fixture")
    assert result.returncode != 0
    assert "MOSAIC_CATALOG_DATASET='real-fixture'" in result.stdout
    assert "real-catalog restore" in result.stdout
    assert not commands


@pytest.mark.parametrize("target", HISTORICAL_TARGETS)
def test_explicit_historical_maintenance_executes_recipe(run_make, target):
    result, commands = run_make(target, allow="1")
    assert result.returncode == 0, result.stderr
    assert commands


def test_guard_falsifier_executes_loader_when_dependency_is_removed(run_make):
    result, commands = run_make("db-load-mosaic", remove_guard=True)
    assert result.returncode == 0, result.stderr
    assert "17_load_normalized_catalog.sql" in commands


def test_schema_bootstrap_does_not_require_historical_opt_in(run_make):
    result, commands = run_make("db-bootstrap-schema", dataset="real-fixture")
    assert result.returncode == 0, result.stderr
    assert "install.sql" in commands
    assert "install_labs.sql" in commands
    assert "17_load_normalized_catalog.sql" not in commands
