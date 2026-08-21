"""Prevent the measured Lab 1 broken state from drifting back to target absence."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lab1_guides_do_not_claim_the_measured_target_is_absent():
    for relative_path in (
        "docs/instructor-guide.md",
        "docs/lab-golden-queries.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "product 2 is absent" not in text
        assert "target moves from absent" not in text
