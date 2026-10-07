"""The commands participants type, exactly as every lab guide shows them.

Guides, terminal messages, completion proofs and the Playground name the same
command, so a participant never translates between a Make target and the
script behind it. The Makefile keeps its targets as maintainer wrappers.
"""

ADVANCE_TO_LAB_2 = "uv run python scripts/lab_state.py advance --lab 1"
STATUS = "uv run python scripts/lab_state.py status"
APPLY_SQL = "uv run python scripts/apply_search_functions.py"
LIST_TOOLS = "uv run python scripts/deploy_agentcore.py tools"
DEPLOY_AGENT = "uv run python scripts/deploy_agentcore.py deploy"
VERIFY_AGENT = "uv run python scripts/deploy_agentcore.py verify"
COMPARE_SETTINGS = "uv run python scripts/lab_exercise.py compare --lab 2"
HNSW_CHECK = "uv run python scripts/hnsw_exercise.py check"


def start(lab: int) -> str:
    return f"uv run python scripts/lab_state.py start --lab {lab}"


def reset(lab: int) -> str:
    return f"uv run python scripts/lab_state.py reset --lab {lab}"


def solution(lab: int) -> str:
    return f"uv run python scripts/lab_state.py solution --lab {lab}"


def validate(lab: int) -> str:
    return f"uv run python scripts/validate_lab.py --lab {lab}"


def complete_lab_3(run_id: str = "<your-run-id>") -> str:
    return f"uv run python scripts/complete_agent.py --run-id {run_id}"


def validate_applied(lab: int) -> str:
    """Check the source and the SQL Aurora last applied, as the guides do."""
    return (
        f"uv run python scripts/lab_state.py validate --lab {lab} "
        '--database-url "$DATABASE_URL"'
    )


def repeat_request(lab: int) -> str:
    """Repeat the lab's saved request against the repaired state."""
    return f"uv run python scripts/lab_terminal.py run --lab {lab} --phase after"


def exercise_check(lab: int) -> str:
    """Grade the participant's own exercise or saved run, without a new answer."""
    return f"uv run python scripts/lab_exercise.py check --lab {lab}"
