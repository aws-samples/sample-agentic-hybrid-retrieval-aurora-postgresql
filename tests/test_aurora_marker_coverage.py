"""Every `@pytest.mark.aurora` test is named by a Make target that runs it.

An aurora-marked test is skipped by `tests/conftest.py` whenever `DATABASE_URL`
is unset, which is every offline CI run. Its only chance to execute is a Make
target that names its file, and both such targets carry a hand-written file
list. A marked test in a file nobody lists therefore runs in no job at all and
reports nothing, while the suite stays green -- the same shape as the failure
`test-aurora-invariants` was created to end, when the Lab 1 anchor invariants
were red for a whole release and surfaced in a clean-account deployment.

That is not hypothetical here. `tests/test_coverage.py` grew five marked tests
covering the live coverage-floor calibration; neither target named the file, and
the Makefile comment still asserted that every marked test lived in two others.
This test derives the expectation from the marker rather than from a list beside
it, so it cannot agree with the drift it is meant to catch.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
MAKEFILE = REPO / "Makefile"

# Both targets that run against Aurora. Splitting the expectation across them is
# deliberate: a marked test may live in either lane, and this test only asserts
# that some Aurora lane names it.
AURORA_TARGETS = ("test-aurora-contracts", "test-aurora-invariants")

MARKER = re.compile(r"^\s*@pytest\.mark\.aurora\b", re.MULTILINE)


def _files_with_aurora_marker() -> set[str]:
    return {
        f"tests/{path.name}"
        for path in sorted(TESTS.glob("test_*.py"))
        if MARKER.search(path.read_text())
    }


def _recipe(makefile: str, target: str) -> str:
    """The target's recipe lines only: what `make <target>` actually executes.

    Scoped to tab-indented lines on purpose. An earlier version read to the next
    column-zero line, which swept in the following comment block -- and those
    comments name test files in prose, so removing a file from the recipe left
    the assertion satisfied by the paragraph explaining why it was there.
    """
    lines = makefile.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"{target}:"):
            recipe = []
            for following in lines[index + 1 :]:
                if not following.startswith("\t"):
                    break
                recipe.append(following)
            return "\n".join(recipe)
    raise AssertionError(f"the Makefile no longer defines a {target} target")


def _files_named_by_aurora_targets() -> set[str]:
    makefile = MAKEFILE.read_text()
    named: set[str] = set()
    for target in AURORA_TARGETS:
        named.update(re.findall(r"tests/test_\w+\.py", _recipe(makefile, target)))
    return named


def test_the_marker_is_actually_in_use():
    """Witness. An empty expectation passes while proving nothing."""
    marked = _files_with_aurora_marker()
    assert marked, "no test file carries @pytest.mark.aurora; this gate is inert"


def test_every_aurora_marked_file_is_run_by_a_make_target():
    marked = _files_with_aurora_marker()
    named = _files_named_by_aurora_targets()
    unrun = sorted(marked - named)
    assert not unrun, (
        f"{unrun} carry @pytest.mark.aurora but no Aurora Make target names them, "
        f"so those tests run in no job: offline CI skips the marker and "
        f"{' and '.join(AURORA_TARGETS)} name only {sorted(named)}. "
        f"Fix: add the file to test-aurora-invariants (or test-aurora-contracts "
        f"if it makes no model calls)."
    )


def test_named_files_exist():
    """A target naming a deleted file passes pytest and proves nothing."""
    missing = sorted(
        name for name in _files_named_by_aurora_targets() if not (REPO / name).exists()
    )
    assert not missing, (
        f"an Aurora Make target names files that do not exist: {missing}"
    )
