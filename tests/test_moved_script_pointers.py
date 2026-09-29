"""Paths that published guides link on GitHub keep a pointer to the moved file.

Workshop builds carry their guides unchanged, and guides published before the
script groups linked `blob/main/scripts/<name>.py`. Each pointer must name a
file that exists and must not become a second implementation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
#: Every path a published guide has linked that later moved.
LINKED_POINTERS = ("scripts/prepare_real_catalog.py", "scripts/embed_real_catalog.py")


@pytest.mark.parametrize("pointer", LINKED_POINTERS)
def test_a_linked_path_points_at_a_file_that_exists(pointer):
    source = (ROOT / pointer).read_text()
    target = re.search(r"^\"\"\"Moved to (\S+)\.$", source, re.MULTILINE)
    assert target, f"{pointer} must open with 'Moved to <path>.'"
    assert (ROOT / target.group(1)).is_file()
    assert "import" not in source, f"{pointer} must not re-export the moved code"


@pytest.mark.parametrize("pointer", LINKED_POINTERS)
def test_nothing_imports_a_pointer(pointer):
    module = pointer.removesuffix(".py").replace("/", ".")
    found = subprocess.run(
        ["git", "grep", "-l", "-E", rf"{re.escape(module)}\b", "--", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert found == []
