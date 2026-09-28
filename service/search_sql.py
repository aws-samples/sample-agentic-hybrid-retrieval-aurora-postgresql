"""The search SQL files, in the order Aurora installs them.

Each file may call functions an earlier one creates, and `LANGUAGE sql` bodies
are checked when they are created. The two lab files therefore sit between the
channels they combine and the weighted fusion and evidence search that reuse
Lab 2's contribution function. `db/sql/install.sql` includes the same files in
the same order; a test holds the two together.
"""

from __future__ import annotations

from pathlib import Path

from service.lab_files import LAB1_SQL, LAB2_SQL, solution_path

ROOT = Path(__file__).resolve().parents[1]

SEARCH_SQL_FILES: tuple[Path, ...] = (
    Path("db/sql/08_search_channels.sql"),
    LAB2_SQL,
    LAB1_SQL,
    Path("db/sql/09_weighted_fusion.sql"),
    Path("db/sql/10_evidence_search.sql"),
)


def search_sql(root: Path = ROOT, *, solutions: bool = False) -> str:
    """The complete search SQL as Aurora installs it.

    Args:
        root: The checkout to read.
        solutions: Read each lab's reference answer instead of the workspace
            copy, for callers that must install working retrieval whatever
            state a participant's lab is in.

    Returns:
        The files joined in install order.
    """
    lab_files = {LAB1_SQL, LAB2_SQL}
    return "\n".join(
        (
            root / (solution_path(path) if solutions and path in lab_files else path)
        ).read_text(encoding="utf-8")
        for path in SEARCH_SQL_FILES
    )
