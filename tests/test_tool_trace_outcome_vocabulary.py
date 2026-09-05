"""`ToolTraceStep.outcome` must accept every value the database enum accepts.

On 2026-09-04 the agent began recording a `denied` trace step for a declined
run, `db/sql/01_schemas_and_types.sql` already carried `denied` in
`mosaic.tool_outcome`, and `ToolTraceStep` still allowed only `success` and
`error`, so building the response for a declined turn would have raised a
validation error after the run had already persisted. The two vocabularies
are read from their sources here so they cannot drift apart again.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from service.models import ToolTraceStep

ROOT = Path(__file__).resolve().parents[1]


def _database_enum_values() -> set[str]:
    sql = (ROOT / "db" / "sql" / "01_schemas_and_types.sql").read_text(encoding="utf-8")
    match = re.search(r"CREATE TYPE mosaic\.tool_outcome AS ENUM \(([^)]*)\)", sql)
    assert match, "mosaic.tool_outcome enum not found in 01_schemas_and_types.sql"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_trace_outcome_literal_matches_the_database_enum() -> None:
    literal = set(get_args(ToolTraceStep.model_fields["outcome"].annotation))
    assert (
        literal == _database_enum_values() == {"success", "denied", "error", "timeout"}
    )


def test_a_denied_trace_step_survives_response_validation() -> None:
    step = ToolTraceStep(
        sequence=1,
        tool="synthesize_cited_answer",
        detail="Recommendation refused; every search this turn came back unanchored.",
        retrieval_run_id=None,
        result_count=0,
        arguments={},
        outcome="denied",
        latency_ms=1,
    )
    assert step.outcome == "denied"
