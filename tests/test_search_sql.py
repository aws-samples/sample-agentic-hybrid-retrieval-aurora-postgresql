"""The search SQL list, the install script and each lab's reference answer agree."""

from __future__ import annotations

import re
from pathlib import Path

from service.lab_files import LAB_FILES, solution_path
from service.search_sql import SEARCH_SQL_FILES

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SQL = ROOT / "db" / "sql" / "install.sql"


def installed_search_files(install_sql: str) -> list[Path]:
    """The search files `install.sql` includes, in order, as repo paths."""
    included = [
        Path("db/sql") / line.split(maxsplit=1)[1]
        for line in install_sql.splitlines()
        if line.startswith("\\ir ")
    ]
    wanted = {path.as_posix() for path in SEARCH_SQL_FILES}
    resolved = [
        Path(re.sub(r"db/sql/\.\./\.\./", "", path.as_posix())) for path in included
    ]
    return [path for path in resolved if path.as_posix() in wanted]


def test_install_sql_includes_the_search_files_in_service_order():
    assert installed_search_files(INSTALL_SQL.read_text()) == list(SEARCH_SQL_FILES)


def test_the_install_order_check_sees_a_swapped_file():
    swapped = INSTALL_SQL.read_text().replace(
        "\\ir ../../labs/lab2_rank/rrf_contribution.sql\n"
        "\\ir ../../labs/lab1_retrieve/hybrid_search.sql\n",
        "\\ir ../../labs/lab1_retrieve/hybrid_search.sql\n"
        "\\ir ../../labs/lab2_rank/rrf_contribution.sql\n",
    )
    assert swapped != INSTALL_SQL.read_text()
    assert installed_search_files(swapped) != list(SEARCH_SQL_FILES)


def test_each_lab_ships_its_reference_answer():
    """The checkout is the working app, so each exercise file is its solution."""
    for lab, exercise in LAB_FILES.items():
        assert (ROOT / exercise).read_bytes() == (
            ROOT / solution_path(exercise)
        ).read_bytes(), f"Lab {lab}: {exercise} differs from its solution"


def test_every_install_include_resolves_to_a_file():
    """psql resolves `\\ir` against the including file's directory."""
    for script in ("install.sql", "install_measurement.sql", "upgrade_snapshot.sql"):
        for line in (ROOT / "db" / "sql" / script).read_text().splitlines():
            if line.startswith("\\ir "):
                target = (ROOT / "db" / "sql" / line.split(maxsplit=1)[1]).resolve()
                assert target.is_file(), f"{script}: {line} does not resolve"
