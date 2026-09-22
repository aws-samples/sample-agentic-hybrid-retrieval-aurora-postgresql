"""A category correction must not conceal missing or rewritten product rows."""

import pytest

from scripts.reconcile_catalog_categories import require_preserved


@pytest.mark.parametrize("present,changed", [(0, 0), (2, 0), (3, 1)])
def test_category_preservation_rejects_deletion_and_other_column_changes(
    present, changed
):
    with pytest.raises(ValueError, match="Category preservation rule.*roll back"):
        require_preserved(3, present, changed)


def test_preservation_accepts_an_unchanged_nonempty_comparison_and_a_noop():
    require_preserved(3, 3, 0)
    require_preserved(0, 0, 0)
