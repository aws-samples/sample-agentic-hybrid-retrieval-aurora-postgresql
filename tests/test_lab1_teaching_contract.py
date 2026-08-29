"""Prevent the measured Lab 1 broken state from drifting back to target presence.

`typo-recovery`'s anchor has been retired twice (see docs/rewrite-losses.md,
LOSS-5 and LOSS-9). `wirless noice canceling hedphones under $200 with long
batery life` left FTS able to recover product 2 through its one correctly-spelled
term. `Sonorra WHC720` replaced it and was worse in a way no gate reported: it
named the model number, so the semantic arm ranked the target first and returned
it with pg_trgm disconnected, leaving the broken state with nothing broken.

The current anchor is `noice cancelng hedfones`. Measured on a live 500,000-row
cluster with the projection fix applied: FTS returns zero rows, the semantic arm
ranks the target far outside its 150-candidate budget, and the broken state
genuinely omits it. A doc that still claims the target "remains visible" or
"still appears" through FTS in the broken state is describing the first retired
anchor, not this one.
"""

import re
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


def test_release_contract_does_not_pin_a_model_dependent_semantic_rank():
    """The invariant is pool absence, not one embedding model's exact position."""
    for relative_path in (
        "data/evals/mosaic_labs_missions.json",
        "deploy/mosaic-bootstrap.sh",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert re.search(r"\bexact rank 2[,]?687\b", text) is None, (
            f"{relative_path} pins an observed semantic rank that has varied "
            "between runs; state only that the target is outside the configured "
            "candidate budget"
        )


def test_lab1_guide_does_not_pin_the_rerankers_final_position():
    """Recall@10 and provenance are stable; the model's exact order is not."""
    text = (ROOT / "docs" / "lab-golden-queries.md").read_text(encoding="utf-8")
    lab1_row = next(line for line in text.splitlines() if "`G-003`" in line)
    assert "final rank 1" not in lab1_row.lower()
