"""Every Python file a Makefile names exists where that Makefile runs it.

CI calls Make targets the test suite never imports, so a moved script can leave
a target broken while every test passes: `make validate-db` once named
`db/scripts/checks/validate_package.py` after the root validator moved.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: A repository-relative `.py` path, optionally under `$(SCHEMA_PACKAGE)`. Paths
#: under any other variable, such as the workshop checkout, are not ours to check.
PYTHON_PATH = re.compile(
    r"(?<![\w./$)-])((?:\$\(SCHEMA_PACKAGE\)/)?[\w.-]+(?:/[\w.-]+)+\.py)(?![\w/])"
)


def missing_paths(makefile: str, base: Path) -> list[str]:
    """The Python paths in one Makefile that do not exist relative to `base`."""
    missing = []
    for match in PYTHON_PATH.finditer(makefile):
        relative = match.group(1).replace("$(SCHEMA_PACKAGE)", "db")
        if not (base / relative).is_file():
            missing.append(match.group(1))
    return sorted(set(missing))


def test_every_root_makefile_python_path_exists():
    assert missing_paths((ROOT / "Makefile").read_text(), ROOT) == []


def test_every_db_package_makefile_python_path_exists():
    assert missing_paths((ROOT / "db" / "Makefile").read_text(), ROOT / "db") == []


def test_a_moved_validator_path_is_caught():
    broken = '\t"$(PYTHON)" "$(SCHEMA_PACKAGE)/scripts/checks/validate_package.py"\n'
    assert missing_paths(broken, ROOT) == [
        "$(SCHEMA_PACKAGE)/scripts/checks/validate_package.py"
    ]
