"""The search SQL files, in the order Aurora installs them.

Each file may call functions an earlier one creates, and `LANGUAGE sql` bodies
are checked when they are created. The two lab files therefore sit between the
channels they combine and the weighted fusion and evidence search that reuse
Lab 2's contribution function. `db/sql/install.sql` includes the same files in
the same order; a test holds the two together.
"""

from __future__ import annotations

from pathlib import Path

from service.catalog_runtime import search_schema
from service.lab_files import LAB1_SQL, LAB2_SQL, solution_path

ROOT = Path(__file__).resolve().parents[1]

#: The fused search function carries the record of which participant SQL Aurora
#: runs. Its applier already owns it, so the record needs no new privilege and
#: no new table, and it changes in the same transaction as the functions do.
FUSED_FUNCTION = (
    "search_hybrid_rrf(text,vector,jsonb,integer,integer,integer,integer,integer,real)"
)
APPLIED_SQL_LABEL = "Participant SQL sha256 "

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


def applied_sql_digest(connection) -> str | None:
    """The participant SQL digest Aurora recorded when the search SQL was last applied.

    Every search reads it on the connection that runs the search, so a search
    record names the SQL that produced it, wherever the search was called from:
    Shop, the API, or the deployed agent through AgentCore Gateway.
    `to_regprocedure` keeps a database without the fused function from failing
    the read; it reports no record instead.
    """
    row = connection.execute(
        "SELECT obj_description(to_regprocedure(%s), 'pg_proc') AS note",
        (f"{search_schema()}.{FUSED_FUNCTION}",),
    ).fetchone()
    note = (row["note"] if isinstance(row, dict) else row[0]) if row else None
    if not note or not note.startswith(APPLIED_SQL_LABEL):
        return None
    return note.removeprefix(APPLIED_SQL_LABEL)
