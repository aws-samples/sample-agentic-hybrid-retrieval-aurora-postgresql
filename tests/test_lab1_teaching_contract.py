"""Prevent the measured Lab 1 broken state from drifting back to target presence.

`typo-recovery`'s anchor query changed 2026-08-27 from `wirless noice canceling
hedphones under $200 with long batery life` to `Sonorra WHC720` (see
docs/rewrite-losses.md, LOSS-5's dated note). Under the retired query the
broken state never hid the target: its one correctly-spelled term
("canceling") let FTS recover product 2 regardless of whether pg_trgm was
connected, which is exactly why that anchor could not teach this lesson.

Under the current anchor, measured on the live cluster: neither FTS nor the
semantic arm can recover the target at all, so the broken state genuinely
omits it. A doc that still claims the target "remains visible" or "still
appears" through FTS in the broken state is describing the retired anchor,
not this one.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lab1_guides_do_not_claim_the_measured_target_is_still_visible_when_broken():
    for relative_path in (
        "docs/instructor-guide.md",
        "docs/lab-golden-queries.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "remains visible through incidental fts" not in text
        assert "still appears through incidental fts" not in text
